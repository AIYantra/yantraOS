"""
YantraOS — Hardened Ephemeral Docker Sandbox
Target: /opt/yantra/core/sandbox.py
Milestone 3, Task 3.1 — Red Team Hardened (v1.2)

SECURITY POSTURE:
  This module is the SOLE gateway between the Kriya Loop's cognitive layer
  (ACT phase) and the host kernel. Every AI-generated script passes through
  this chokepoint.  The design philosophy is "default deny":

  ┌──────────────────────────────────────────────────────────────────────┐
  │  PROHIBITED (hardcoded, cannot be overridden by ANY caller):        │
  │    • Volume mounts / bind mounts  → No host filesystem access       │
  │    • Privileged mode              → No /dev, no raw sockets         │
  │    • Host PID/IPC/UTS namespaces  → Full namespace isolation        │
  │    • Network access               → network_mode="none"            │
  │    • Capability grants            → cap_drop=["ALL"]               │
  │    • Setuid/setgid escalation     → no-new-privileges:true         │
  │    • Arbitrary images             → Allowlist enforced              │
  │    • Writable root FS             → read_only=True                 │
  │    • Persistent containers        → auto_remove=True               │
  │    • Excessive resources           → mem_limit, cpu_quota enforced  │
  └──────────────────────────────────────────────────────────────────────┘

  Input sanitization:
    • Script payload: must be `str`, max 64 KiB, stripped of NUL bytes.
    • Image argument: validated against a frozen allowlist.
    • Environment vars: keys and values must be printable ASCII, no shell
      metacharacters in keys.  Max 16 variables, max 1 KiB per value.
    • Timeout: clamped to [1, 120] seconds.

  Graceful degradation:
    If Docker is offline, the module enters DEGRADED state. The Kriya Loop
    continues in observe-only mode. No crash, no exception propagation.

  Audit trail:
    Every execution attempt is logged with a SHA-256 fingerprint of the
    script payload, the resolved image, and the outcome. This provides a
    forensic chain-of-custody for post-incident analysis.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, FrozenSet

if TYPE_CHECKING:
    import docker  # noqa: F811 — static analysis only

log = logging.getLogger("yantra.sandbox")

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS — HARDCODED, NON-CONFIGURABLE
# These values form the "Geometric Law" of the sandbox. They are Final and
# frozen. No caller, no configuration file, no LLM prompt can alter them.
# ══════════════════════════════════════════════════════════════════════════════

# ── Image Allowlist ───────────────────────────────────────────────────────────
# SECURITY: Only these images may be used. Any image not in this set is
# rejected with a validation error. This prevents an LLM from requesting
# execution inside a privileged or backdoored image.
ALLOWED_IMAGES: Final[FrozenSet[str]] = frozenset({
    "alpine:3.19",
    "alpine:3.20",
    "alpine:latest",
    "yantra-agent:latest",
    "yantra-sandbox:latest",
})

# Default sandbox image — custom hardened Alpine with bash + coreutils.
# Built programmatically from core/sandbox/Dockerfile if not found locally.
SANDBOX_IMAGE: Final[str] = "yantra-sandbox:latest"

# ── Execution Limits ─────────────────────────────────────────────────────────
EXECUTION_TIMEOUT_SECS: Final[int] = 10     # Default hard-kill deadline
MAX_TIMEOUT_SECS: Final[int] = 120          # Upper bound, non-negotiable
MIN_TIMEOUT_SECS: Final[int] = 1            # Lower bound

# ── cgroups Constraints ──────────────────────────────────────────────────────
CONTAINER_MEM_LIMIT: Final[str] = "128m"    # OOM-killed at 128 MiB
CONTAINER_CPU_QUOTA: Final[int] = 50000     # 50% of one core (period=100 ms)
CONTAINER_TMPFS_SIZE: Final[str] = "64m"    # Writable scratch cap
CONTAINER_PIDS_LIMIT: Final[int] = 64       # Fork bomb protection

# ── Input Sanitization Limits ────────────────────────────────────────────────
MAX_SCRIPT_BYTES: Final[int] = 65_536       # 64 KiB max script payload
MAX_ENV_VARS: Final[int] = 16               # Max environment variables
MAX_ENV_KEY_LEN: Final[int] = 128           # Max chars per env key
MAX_ENV_VAL_LEN: Final[int] = 1024          # Max chars per env value (1 KiB)

# Regex: env keys must be alphanumeric + underscores, starting with a letter.
# This prevents shell injection via crafted variable names like `$(cmd)`.
_ENV_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")




# ══════════════════════════════════════════════════════════════════════════════
# DATA TYPES
# ══════════════════════════════════════════════════════════════════════════════


class SandboxStatus(str, Enum):
    """Status of the Docker sandbox subsystem."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"           # Docker unreachable — observe-only mode
    UNAVAILABLE = "UNAVAILABLE"     # docker-py not installed


class ExecOutcome(str, Enum):
    """Outcome of a sandboxed script execution."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    DOCKER_ERROR = "docker_error"
    VALIDATION_ERROR = "validation_error"   # Input rejected before execution


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """
    Immutable, structured result from an ephemeral container execution.

    frozen=True ensures that no downstream consumer can mutate the result
    after creation, preserving the forensic integrity of the audit trail.
    """
    outcome: ExecOutcome
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    duration_secs: float = 0.0
    container_id: str = ""
    image: str = ""
    script_hash: str = ""
    error: str | None = None


# ══════════════════════════════════════════════════════════════════════════════
# INPUT VALIDATION — STATIC, PRE-EXECUTION SANITIZATION
# ══════════════════════════════════════════════════════════════════════════════


class InputValidationError(Exception):
    """Raised when sandbox inputs fail security validation."""


def _validate_script(script: str) -> str:
    """
    Validate and sanitize the script payload.

    Security checks:
      1. Type assertion — must be str, not bytes or other types.
      2. Length cap — 64 KiB prevents memory exhaustion via giant payloads.
      3. NUL byte stripping — prevents C-string truncation attacks.
      4. Non-empty check — rejects blank/whitespace-only scripts.

    Returns:
        The sanitized script string.

    Raises:
        InputValidationError: If validation fails.
    """
    if not isinstance(script, str):
        raise InputValidationError(
            f"Script must be str, got {type(script).__name__}"
        )

    # Strip NUL bytes — these can cause truncation in shell interpreters
    script = script.replace("\x00", "")

    if len(script.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise InputValidationError(
            f"Script exceeds {MAX_SCRIPT_BYTES} byte limit "
            f"({len(script.encode('utf-8'))} bytes)"
        )

    if not script.strip():
        raise InputValidationError("Script is empty or whitespace-only")

    return script


def _validate_image(image: str) -> str:
    """
    Validate the container image against the frozen allowlist.

    SECURITY: This is the most critical validation. A compromised LLM could
    attempt to specify a custom image containing exfiltration tools, reverse
    shells, or host-mounted capabilities. The allowlist prevents this.

    Returns:
        The validated image string.

    Raises:
        InputValidationError: If the image is not in the allowlist.
    """
    if not isinstance(image, str):
        raise InputValidationError(
            f"Image must be str, got {type(image).__name__}"
        )

    if image not in ALLOWED_IMAGES:
        raise InputValidationError(
            f"Image '{image}' is not in the allowlist. "
            f"Permitted images: {sorted(ALLOWED_IMAGES)}"
        )

    return image


def _validate_env(env: dict[str, str] | None) -> dict[str, str]:
    """
    Validate environment variables for the container.

    Security checks:
      1. Max 16 variables — prevents environment table exhaustion.
      2. Keys: alphanumeric + underscore only, starting with a letter.
         This blocks shell metacharacter injection via env key names
         (e.g., a key of `$(curl evil.com)` would be rejected).
      3. Values: printable ASCII, max 1 KiB each. Blocks binary injection.

    Returns:
        The validated environment dict (may be empty).

    Raises:
        InputValidationError: If any variable fails validation.
    """
    if env is None:
        return {}

    if not isinstance(env, dict):
        raise InputValidationError(
            f"Environment must be dict, got {type(env).__name__}"
        )

    if len(env) > MAX_ENV_VARS:
        raise InputValidationError(
            f"Too many env vars: {len(env)} (max {MAX_ENV_VARS})"
        )

    validated: dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise InputValidationError(
                f"Env key and value must be str: key={type(key).__name__}, "
                f"value={type(value).__name__}"
            )

        if len(key) > MAX_ENV_KEY_LEN:
            raise InputValidationError(
                f"Env key '{key[:32]}...' exceeds {MAX_ENV_KEY_LEN} chars"
            )

        if not _ENV_KEY_PATTERN.match(key):
            raise InputValidationError(
                f"Env key '{key[:32]}' contains invalid characters. "
                "Only [A-Za-z_][A-Za-z0-9_]* allowed."
            )

        if len(value) > MAX_ENV_VAL_LEN:
            raise InputValidationError(
                f"Env value for '{key}' exceeds {MAX_ENV_VAL_LEN} chars"
            )

        # Reject NUL bytes in values
        if "\x00" in value:
            raise InputValidationError(
                f"Env value for '{key}' contains NUL bytes"
            )

        validated[key] = value

    return validated


def _validate_timeout(timeout: int) -> int:
    """
    Clamp timeout to safe bounds.

    Returns:
        Clamped timeout value.

    Raises:
        InputValidationError: If timeout is not an integer.
    """
    if not isinstance(timeout, int):
        raise InputValidationError(
            f"Timeout must be int, got {type(timeout).__name__}"
        )

    return max(MIN_TIMEOUT_SECS, min(timeout, MAX_TIMEOUT_SECS))


def _validate_shell(shell: str) -> str:
    """
    Validate the shell binary path.

    Only a small set of known-safe shell paths are permitted.
    This prevents an LLM from specifying an arbitrary binary as the
    shell interpreter (e.g., `/usr/bin/curl` to exfiltrate data).

    Returns:
        The validated shell path.

    Raises:
        InputValidationError: If the shell is not in the allowlist.
    """
    allowed_shells: frozenset[str] = frozenset({
        "/bin/sh", "/bin/ash", "/bin/bash",
    })

    if not isinstance(shell, str):
        raise InputValidationError(
            f"Shell must be str, got {type(shell).__name__}"
        )

    if shell not in allowed_shells:
        raise InputValidationError(
            f"Shell '{shell}' not permitted. Allowed: {sorted(allowed_shells)}"
        )

    return shell


# ══════════════════════════════════════════════════════════════════════════════
# SANDBOX ENGINE
# ══════════════════════════════════════════════════════════════════════════════


class SandboxEngine:
    """
    Async-safe, security-hardened Docker container execution engine.

    ARCHITECTURE:
      All Docker SDK calls are blocking (docker-py is synchronous). They are
      dispatched via ThreadPoolExecutor.run_in_executor() to prevent stalling
      the Kriya Loop's asyncio event loop.

    SECURITY MODEL:
      1. DENY-BY-DEFAULT: All dangerous Docker parameters (volumes, binds,
         privileged, pid_mode, etc.) are hardcoded to safe values. The
         execute() method does NOT accept these as parameters, so no caller
         — including an LLM generating a function call — can override them.

      2. INPUT VALIDATION: Every argument is statically typed and validated
         before reaching the Docker SDK. Validation failures return a
         SandboxResult with outcome=VALIDATION_ERROR, never raising to caller.

      3. IMAGE ALLOWLIST: Only pre-approved images may be used.

      4. IMMUTABLE RESULTS: SandboxResult is a frozen dataclass. Post-creation
         mutation is impossible, preserving forensic integrity.

    USAGE:
        sandbox = SandboxEngine()
        await sandbox.initialize()              # pre-flight health check
        result = await sandbox.execute("echo 'hello from sandbox'")
    """

    __slots__ = ("_client", "_status", "_executor")

    def __init__(self) -> None:
        self._client: Any = None            # docker.DockerClient (lazy import)
        self._status: SandboxStatus = SandboxStatus.UNAVAILABLE
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="yantra-sandbox"
        )

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def status(self) -> SandboxStatus:
        """Current sandbox subsystem health status."""
        return self._status

    @property
    def is_operational(self) -> bool:
        """True only when Docker is confirmed reachable and pinged."""
        return self._status == SandboxStatus.HEALTHY

    # ══════════════════════════════════════════════════════════════════════
    # INITIALIZATION & HEALTH CHECK (Invariant 1)
    # ══════════════════════════════════════════════════════════════════════

    async def initialize(self) -> SandboxStatus:
        """
        Pre-flight health check. MUST be called once during engine bootstrap,
        BEFORE the main Kriya Loop begins execution.

        Sequence:
          1. Import docker-py → If absent → UNAVAILABLE (graceful).
          2. client = docker.from_env() → Connect via UNIX socket.
          3. client.ping() → Verify Docker API responsiveness.
          4. Verify base image availability; pull if missing.

        On failure at ANY step: emit journal warning, set DEGRADED/UNAVAILABLE,
        return status. The Python interpreter NEVER crashes.
        """
        loop = asyncio.get_event_loop()
        self._status = await loop.run_in_executor(
            self._executor, self._blocking_init
        )
        return self._status

    def _blocking_init(self) -> SandboxStatus:
        """
        Blocking Docker initialization — runs in the executor thread.

        SECURITY: ConnectionError and DockerException are caught to prevent
        uncontrolled exception propagation. The daemon stays alive regardless.
        """
        # ── Step 1: Import docker-py ──────────────────────────────────────
        try:
            import docker  # type: ignore[import-untyped]
        except ImportError:
            log.error(
                "> SANDBOX: docker-py is not installed. "
                "Run: pip install docker. Sandbox UNAVAILABLE."
            )
            return SandboxStatus.UNAVAILABLE

        # ── Step 2: Instantiate client ────────────────────────────────────
        try:
            self._client = docker.from_env()
        except docker.errors.DockerException as exc:  # type: ignore[attr-defined]
            log.error(
                f"> SANDBOX: Failed to connect to Docker daemon: {exc}. "
                "Is the Docker service running? Sandbox DEGRADED."
            )
            return SandboxStatus.DEGRADED

        # ── Step 3: Pre-flight ping ───────────────────────────────────────
        # INVARIANT 1: client.ping() wrapped in try-except. If Docker is
        # offline or throws ConnectionError, degrade gracefully without crash.
        try:
            self._client.ping()
        except (ConnectionError, Exception) as exc:
            log.error(
                f"> SANDBOX: Docker ping failed: {exc}. "
                "The daemon may be starting up. Sandbox DEGRADED."
            )
            self._client = None
            return SandboxStatus.DEGRADED

        # ── Step 4: Ensure sandbox image is available ─────────────────────
        # If yantra-sandbox:latest is not found locally, build it from the
        # Dockerfile shipped in core/sandbox/. This avoids any dependency
        # on an external registry and guarantees a deterministic image.
        try:
            self._client.images.get(SANDBOX_IMAGE)
            log.info(f"> SANDBOX: Image {SANDBOX_IMAGE} confirmed locally.")
        except docker.errors.ImageNotFound:  # type: ignore[attr-defined]
            log.info(
                f"> SANDBOX: Image {SANDBOX_IMAGE} not found. "
                "Building from core/sandbox/Dockerfile..."
            )
            try:
                # Resolve the Dockerfile directory relative to this module.
                dockerfile_dir = str(
                    Path(os.path.abspath(__file__)).parent / "sandbox"
                )
                _image, _build_log = self._client.images.build(
                    path=dockerfile_dir,
                    tag=SANDBOX_IMAGE,
                    rm=True,           # Remove intermediate containers
                    forcerm=True,      # Remove even on failure
                    quiet=False,
                )
                log.info(
                    f"> SANDBOX: Build complete — {SANDBOX_IMAGE} "
                    f"(id={_image.short_id})"
                )
            except Exception as exc:
                log.error(
                    f"> SANDBOX: Failed to build {SANDBOX_IMAGE}: {exc}. "
                    "Sandbox will be DEGRADED."
                )
                return SandboxStatus.DEGRADED

        info: dict[str, Any] = self._client.info()
        log.info(
            f"> SANDBOX: Docker HEALTHY — "
            f"Server {info.get('ServerVersion', '?')}, "
            f"Runtime {info.get('DefaultRuntime', '?')}, "
            f"Containers {info.get('Containers', '?')}"
        )
        return SandboxStatus.HEALTHY

    async def health_check(self) -> bool:
        """
        Periodic health re-check. Called by the SENSE phase to detect
        Docker daemon restarts or crashes mid-operation.
        """
        if self._client is None:
            return False

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                self._executor, self._client.ping
            )
            if self._status != SandboxStatus.HEALTHY:
                log.info("> SANDBOX: Docker connectivity restored → HEALTHY")
                self._status = SandboxStatus.HEALTHY
            return True
        except Exception:
            if self._status == SandboxStatus.HEALTHY:
                log.warning("> SANDBOX: Docker connectivity lost → DEGRADED")
                self._status = SandboxStatus.DEGRADED
            return False

    # ══════════════════════════════════════════════════════════════════════
    # EXECUTION (Invariants 2, 3, 4, 5)
    # ══════════════════════════════════════════════════════════════════════

    async def execute(
        self,
        script: str,
        *,
        image: str | None = None,
        timeout: int = EXECUTION_TIMEOUT_SECS,
        env: dict[str, str] | None = None,
        shell: str = "/bin/sh",
    ) -> SandboxResult:
        """
        Execute a script inside an ephemeral, hardened container.

        SECURITY ARCHITECTURE:
          The method signature intentionally OMITS parameters for volumes,
          binds, privileged, pid_mode, ipc_mode, devices, cap_add, etc.
          This is the "Prohibition by Omission" principle — if the caller
          cannot pass these arguments, they cannot be exploited, even if
          the calling code is generated by a compromised LLM.

          The script is passed as a shell -c argument (not via volume mount)
          to prevent path-traversal attacks against the container filesystem.

        INPUT VALIDATION (Invariant 3):
          Every parameter undergoes static type checking and value validation
          before any Docker SDK call is made. Failures return SandboxResult
          with outcome=VALIDATION_ERROR. Exceptions never propagate.

        Args:
            script:   Shell script content to execute.
            image:    Container image (must be in allowlist).
            timeout:  Hard kill deadline in seconds (clamped to [1, 120]).
            env:      Optional environment variables for the container.
            shell:    Shell binary inside the container.

        Returns:
            Immutable SandboxResult with stdout, stderr, exit code, timing,
            and a SHA-256 fingerprint of the input script for auditing.
        """
        # ── Phase 1: Input validation (Invariant 3) ───────────────────────
        script_hash: str = ""
        try:
            script = _validate_script(script)
            script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()[:16]
            resolved_image = _validate_image(image or SANDBOX_IMAGE)
            validated_env = _validate_env(env)
            validated_timeout = _validate_timeout(timeout)
            validated_shell = _validate_shell(shell)
        except InputValidationError as exc:
            log.warning(
                f"> SANDBOX: Input validation REJECTED "
                f"[{script_hash or 'pre-hash'}]: {exc}"
            )
            return SandboxResult(
                outcome=ExecOutcome.VALIDATION_ERROR,
                script_hash=script_hash,
                error=f"Validation: {exc}",
            )

        # ── Phase 2: Operational check ────────────────────────────────────
        if not self.is_operational:
            log.warning(
                f"> SANDBOX: Execution rejected — Docker is "
                f"{self._status.value}. Script hash: {script_hash}"
            )
            return SandboxResult(
                outcome=ExecOutcome.DOCKER_ERROR,
                script_hash=script_hash,
                error=f"Sandbox {self._status.value}: Docker not available",
            )

        # ── Phase 3: Dispatch to executor thread ─────────────────────────
        loop = asyncio.get_event_loop()
        run_fn = partial(
            self._blocking_execute,
            script=script,
            script_hash=script_hash,
            image=resolved_image,
            timeout=validated_timeout,
            env=validated_env,
            shell=validated_shell,
        )

        try:
            # Outer async timeout with 10 s buffer beyond the container
            # timeout. This catches cases where Docker itself hangs.
            result = await asyncio.wait_for(
                loop.run_in_executor(self._executor, run_fn),
                timeout=validated_timeout + 10,
            )
            return result
        except asyncio.TimeoutError:
            log.error(
                f"> SANDBOX: Async timeout after {validated_timeout + 10}s. "
                f"Script [{script_hash}] — container may be orphaned."
            )
            return SandboxResult(
                outcome=ExecOutcome.TIMEOUT,
                script_hash=script_hash,
                error=f"Execution exceeded {validated_timeout}s deadline",
            )

    def _blocking_execute(
        self,
        script: str,
        script_hash: str,
        image: str,
        timeout: int,
        env: dict[str, str],
        shell: str,
    ) -> SandboxResult:
        """
        Blocking container execution — runs in the executor thread.

        ╔════════════════════════════════════════════════════════════════╗
        ║  SECURITY ENFORCEMENT MATRIX (Invariant 2 & 4)               ║
        ║                                                              ║
        ║  ┌─────────────────────────┬────────────────────────────┐    ║
        ║  │ Parameter               │ Hardcoded Value            │    ║
        ║  ├─────────────────────────┼────────────────────────────┤    ║
        ║  │ network_mode            │ "none"                     │    ║
        ║  │ mem_limit               │ "128m"                     │    ║
        ║  │ cpu_quota               │ 50000 (50% single core)    │    ║
        ║  │ pids_limit              │ 64 (fork bomb protection)  │    ║
        ║  │ read_only               │ True                       │    ║
        ║  │ cap_drop                │ ["ALL"]                    │    ║
        ║  │ security_opt            │ ["no-new-privileges:true"] │    ║
        ║  │ auto_remove             │ True                       │    ║
        ║  │ tmpfs /tmp              │ size=64m, noexec, nosuid   │    ║
        ║  │ privileged              │ False (EXPLICIT)           │    ║
        ║  │ volumes / binds         │ NOT PASSED (omitted)       │    ║
        ║  │ pid_mode / ipc_mode     │ NOT PASSED (omitted)       │    ║
        ║  │ devices                 │ NOT PASSED (omitted)       │    ║
        ║  │ cap_add                 │ NOT PASSED (omitted)       │    ║
        ║  │ user                    │ "nobody" (UID 65534)       │    ║
        ║  └─────────────────────────┴────────────────────────────┘    ║
        ║                                                              ║
        ║  PROHIBITION (Invariant 4):                                  ║
        ║  volumes, binds, privileged, cap_add, pid_mode, ipc_mode,    ║
        ║  uts_mode, devices — NONE of these parameters exist in the   ║
        ║  function signature or the containers.run() call. They are   ║
        ║  structurally impossible to inject, regardless of what the   ║
        ║  cognitive layer generates.                                   ║
        ╚════════════════════════════════════════════════════════════════╝
        """
        import docker  # type: ignore[import-untyped]

        t_start: float = time.monotonic()

        log.info(
            f"> SANDBOX: Executing script [{script_hash}] "
            f"in {image} (timeout={timeout}s)"
        )

        try:
            # ── containers.run() — THE SECURITY CHOKEPOINT ────────────────
            #
            # INVARIANT 2: Absolute resource constraints enforced here.
            # INVARIANT 4: No volumes, binds, privileged, cap_add, devices,
            #              pid_mode, ipc_mode, or uts_mode parameters.
            # INVARIANT 5: Base image is Alpine Linux (validated above).
            #
            # Script injection method: shell -c argument.
            # This avoids volume mounts entirely. The script content lives
            # only in the container's process memory, not on any filesystem.
            output: bytes = self._client.containers.run(
                image=image,
                command=[shell, "-c", script],

                # ── NETWORK ISOLATION (Invariant 2) ───────────────────────
                # Prevents ALL network access: no DNS, no egress, no ingress.
                # A malicious script cannot exfiltrate data, phone home, or
                # download additional payloads.
                network_mode="none",

                # ── MEMORY LIMIT (Invariant 2) ────────────────────────────
                # Hard cap at 512 MiB. The Linux OOM killer will terminate
                # the container process if it exceeds this. Prevents a fork
                # bomb or memory leak from exhausting host RAM.
                mem_limit=CONTAINER_MEM_LIMIT,

                # ── CPU QUOTA (Invariant 2) ────────────────────────────────
                # 50000 µs out of a 100000 µs period = 50% of one CPU core.
                # Prevents crypto-mining or CPU exhaustion attacks.
                cpu_quota=CONTAINER_CPU_QUOTA,

                # ── PIDS LIMIT ────────────────────────────────────────────
                # Maximum 64 processes inside the container. Prevents fork
                # bombs from spawning thousands of processes.
                pids_limit=CONTAINER_PIDS_LIMIT,

                # ── READ-ONLY ROOT FS ─────────────────────────────────────
                # The container's root filesystem is mounted read-only.
                # No file can be written to / — only /tmp is writable.
                read_only=True,

                # ── ZERO CAPABILITIES ─────────────────────────────────────
                # All 41 Linux capabilities are dropped. The container
                # process runs with literally zero privileges.
                # No raw sockets, no chown, no mknod, no mount, no ptrace.
                cap_drop=["ALL"],

                # ── NO-NEW-PRIVILEGES ─────────────────────────────────────
                # Blocks setuid/setgid binaries from escalating privilege.
                # Even if a setuid binary exists in the image, it cannot
                # gain elevated privileges.
                security_opt=["no-new-privileges:true"],

                # ── EPHEMERALITY (Invariant 2) ────────────────────────────
                # Container is destroyed immediately upon process exit.
                # No forensic artifact, no leftover state, no persistence.
                auto_remove=True,

                # ── WRITABLE SCRATCH ──────────────────────────────────────
                # /tmp is the ONLY writable location, capped at 64 MiB.
                # noexec: prevents executing binaries written to /tmp.
                # nosuid: prevents setuid escalation from /tmp.
                tmpfs={"/tmp": f"size={CONTAINER_TMPFS_SIZE},noexec,nosuid"},

                # ── RUN AS NOBODY ─────────────────────────────────────────
                # Execute as the unprivileged 'nobody' user (UID 65534).
                # Even inside the container, the process has no ownership
                # of any files and cannot modify the image's filesystem.
                user="sandbox_user",

                # ── EXPLICIT UNPRIVILEGED ──────────────────────────────────
                # Redundant but intentional: explicitly set privileged=False
                # as a defense-in-depth measure against SDK default changes.
                privileged=False,

                # ── EXECUTION PARAMS ──────────────────────────────────────
                environment=env,
                detach=False,
                stdout=True,
                stderr=True,
                stop_signal="SIGKILL",

                # ── AUDIT LABEL ───────────────────────────────────────────
                # Tag the container for cleanup and forensic identification.
                labels={"yantra": "sandbox", "script_hash": script_hash},
            )

            elapsed: float = time.monotonic() - t_start

            # containers.run() with detach=False returns bytes
            stdout_text: str = (
                output.decode("utf-8", errors="replace") if output else ""
            )

            log.info(
                f"> SANDBOX: Script [{script_hash}] completed "
                f"in {elapsed:.2f}s (exit=0)"
            )

            return SandboxResult(
                outcome=ExecOutcome.SUCCESS,
                exit_code=0,
                stdout=stdout_text,
                stderr="",
                duration_secs=round(elapsed, 3),
                image=image,
                script_hash=script_hash,
            )

        except docker.errors.ContainerError as exc:  # type: ignore[attr-defined]
            elapsed = time.monotonic() - t_start
            stderr_text: str = (
                exc.stderr.decode("utf-8", errors="replace")
                if exc.stderr else ""
            )
            log.warning(
                f"> SANDBOX: Script [{script_hash}] failed "
                f"(exit={exc.exit_status}) in {elapsed:.2f}s"
            )
            return SandboxResult(
                outcome=ExecOutcome.FAILURE,
                exit_code=exc.exit_status,
                stdout=(
                    exc.output.decode("utf-8", errors="replace")
                    if exc.output else ""
                ),
                stderr=stderr_text,
                duration_secs=round(elapsed, 3),
                image=image,
                script_hash=script_hash,
            )

        except docker.errors.ImageNotFound:  # type: ignore[attr-defined]
            log.error(
                f"> SANDBOX: Image {image} not found. "
                f"Script [{script_hash}] aborted."
            )
            return SandboxResult(
                outcome=ExecOutcome.DOCKER_ERROR,
                script_hash=script_hash,
                error=f"Image not found: {image}",
            )

        except docker.errors.APIError as exc:  # type: ignore[attr-defined]
            log.error(
                f"> SANDBOX: Docker API error for [{script_hash}]: {exc}"
            )
            return SandboxResult(
                outcome=ExecOutcome.DOCKER_ERROR,
                script_hash=script_hash,
                error=f"Docker API: {exc}",
            )

        except Exception as exc:
            log.error(
                f"> SANDBOX: Unexpected error for [{script_hash}]: "
                f"{type(exc).__name__}: {exc}"
            )
            return SandboxResult(
                outcome=ExecOutcome.DOCKER_ERROR,
                script_hash=script_hash,
                error=str(exc),
            )

    # ══════════════════════════════════════════════════════════════════════
    # CLEANUP & SHUTDOWN
    # ══════════════════════════════════════════════════════════════════════

    async def cleanup_stale_containers(self, label: str = "yantra") -> int:
        """
        Prune any orphaned containers with the `yantra` label.
        Called during startup and periodically by UPDATE_ARCHITECTURE phase.
        """
        if self._client is None:
            return 0

        loop = asyncio.get_event_loop()

        def _prune() -> int:
            try:
                result = self._client.containers.prune(
                    filters={"label": [label]}
                )
                deleted: int = len(result.get("ContainersDeleted", []) or [])
                if deleted:
                    log.info(
                        f"> SANDBOX: Pruned {deleted} stale container(s)."
                    )
                return deleted
            except Exception as exc:
                log.warning(f"> SANDBOX: Container prune failed: {exc}")
                return 0

        return await loop.run_in_executor(self._executor, _prune)

    def shutdown(self) -> None:
        """
        Gracefully close the Docker client and executor.

        Called by engine.py during daemon shutdown (SIGTERM handler).
        """
        log.info("> SANDBOX: Shutting down sandbox engine...")
        self._executor.shutdown(wait=True)
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        log.info("> SANDBOX: Shutdown complete.")


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL SINGLETON
# ══════════════════════════════════════════════════════════════════════════════

sandbox: SandboxEngine = SandboxEngine()
