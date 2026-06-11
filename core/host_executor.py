"""
YantraOS — Host Executor Daemon (Privileged Intent Gateway)
Target: /opt/yantra/core/host_executor.py

Root-level asyncio daemon that binds a UNIX domain socket at
/run/yantra/executor.sock and processes strictly typed JSON intents
from the unprivileged Kriya Loop.

Architecture:
  yantra.service (User=yantra_daemon)
       │
       │  JSON intent via UDS
       ▼
  yantra-host-executor.service (User=root)
       │
       ├─ Schema validation (reject raw shell strings)
       ├─ BTRFS pre-flight snapshot (/usr/bin/yantra-snapshot --pre-flight)
       └─ Hardcoded command dispatch (no shell=True)

Security invariants:
  • Raw shell strings are REJECTED. Only typed intent schemas are accepted.
  • Every intent is gated by a BTRFS snapshot. If the snapshot fails,
    the intent is rejected with a FATAL response — no execution occurs.
  • Command dispatch uses a hardcoded mapping table. All subprocess calls
    use explicit argument lists — never shell=True.
  • Socket permissions: root:yantra 0660 — only yantra group can connect.
  • Input sanitization: target fields are validated against [a-zA-Z0-9_.-]
    to prevent injection in command arguments.
"""

from __future__ import annotations

import asyncio
import grp
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("yantra.host_executor")

# ── Constants ─────────────────────────────────────────────────────────────────

SOCKET_PATH: str = "/run/yantra/executor.sock"
SOCKET_MODE: int = 0o660
SOCKET_GROUP: str = "yantra"

SNAPSHOT_BIN: str = "/usr/bin/yantra-snapshot"
SNAPSHOT_TIMEOUT_SECS: int = 60

# Maximum payload size from client (16 KiB). Prevents memory exhaustion
# from a malicious or buggy client flooding the socket.
MAX_PAYLOAD_BYTES: int = 16384

# Input sanitization regex — ONLY alphanumeric, underscore, hyphen, dot.
# Prevents injection in command arguments.
_SAFE_TARGET_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_.\-]+$")

# ── Intent Schema ─────────────────────────────────────────────────────────────
# Each valid intent type maps to a hardcoded command array factory.
# NO raw shell strings are ever accepted. The mapping is exhaustive —
# any intent not in this table is rejected.

_VALID_INTENTS: set[str] = {
    "SYSTEM_UPDATE",
    "RESTART_DAEMON",
    "ENABLE_DAEMON",
    "DISABLE_DAEMON",
    "STOP_DAEMON",
    "PRUNE_SNAPSHOTS",
    "SYNC_CLOCK",
    "RELOAD_DAEMON_CONFIGS",
}


# ── Input Validation ──────────────────────────────────────────────────────────


def _validate_target(target: str) -> str:
    """
    Sanitize the target field from an intent payload.

    Only allows [a-zA-Z0-9_.-] to prevent injection of shell
    metacharacters, path traversal, or null bytes into subprocess args.

    Args:
        target: Raw target string from the JSON payload.

    Returns:
        The validated target string (unchanged if valid).

    Raises:
        ValueError: If the target contains disallowed characters.
    """
    if not target:
        raise ValueError("Intent target cannot be empty.")
    if len(target) > 128:
        raise ValueError(
            f"Intent target exceeds 128 characters ({len(target)}). "
            "Possible injection attempt."
        )
    if not _SAFE_TARGET_RE.match(target):
        raise ValueError(
            f"SECURITY: Target '{target}' contains disallowed characters. "
            "Only [a-zA-Z0-9_.-] are permitted."
        )
    return target


# ── Command Dispatch Table ────────────────────────────────────────────────────
# Each intent type maps to a function that returns (cmd_list, description).
# The command list is passed directly to subprocess.run() — no shell=True.


def _build_command(intent: str, target: str) -> tuple[list[str], str]:
    """
    Map a validated intent + target to a concrete subprocess command array.

    Args:
        intent: The validated intent type (from _VALID_INTENTS).
        target: The sanitized target string.

    Returns:
        Tuple of (command_list, human_description).

    Raises:
        ValueError: If the intent is not in the dispatch table.
    """
    dispatch: dict[str, tuple[list[str], str]] = {
        "SYSTEM_UPDATE": (
            ["/usr/bin/pacman", "-Syu", "--noconfirm"],
            "Full system upgrade via pacman",
        ),
        "RESTART_DAEMON": (
            ["/usr/bin/systemctl", "restart", target],
            f"Restart systemd unit: {target}",
        ),
        "ENABLE_DAEMON": (
            ["/usr/bin/systemctl", "enable", "--now", target],
            f"Enable and start systemd unit: {target}",
        ),
        "DISABLE_DAEMON": (
            ["/usr/bin/systemctl", "disable", "--now", target],
            f"Disable and stop systemd unit: {target}",
        ),
        "STOP_DAEMON": (
            ["/usr/bin/systemctl", "stop", target],
            f"Stop systemd unit: {target}",
        ),
        "PRUNE_SNAPSHOTS": (
            ["/usr/bin/yantra-snapshot", "--prune"],
            "Prune old BTRFS snapshots",
        ),
        "SYNC_CLOCK": (
            ["/usr/bin/timedatectl", "set-ntp", "true"],
            "Enable NTP time synchronization",
        ),
        "RELOAD_DAEMON_CONFIGS": (
            ["/usr/bin/systemctl", "daemon-reload"],
            "Reload all systemd unit files",
        ),
    }

    if intent not in dispatch:
        raise ValueError(f"No command mapping for intent '{intent}'.")

    return dispatch[intent]


# ── BTRFS Pre-Flight Snapshot Gate ────────────────────────────────────────────


def _execute_preflight_snapshot() -> tuple[bool, str]:
    """
    Synchronously trigger the BTRFS pre-flight snapshot via the
    50-yantra-autosnap.hook mechanism.

    Calls:
        /usr/bin/yantra-snapshot --pre-flight

    Returns:
        Tuple of (success: bool, message: str).
        On failure, the message contains the stderr output for FATAL logging.
    """
    if not Path(SNAPSHOT_BIN).exists():
        return False, (
            f"FATAL: Snapshot binary not found at {SNAPSHOT_BIN}. "
            "Cannot gate intent execution without BTRFS pre-flight."
        )

    try:
        result: subprocess.CompletedProcess[bytes] = subprocess.run(
            [SNAPSHOT_BIN, "--pre-flight"],
            capture_output=True,
            timeout=SNAPSHOT_TIMEOUT_SECS,
            check=False,
        )

        if result.returncode == 0:
            stdout: str = result.stdout.decode("utf-8", errors="replace").strip()
            log.info(f"> EXECUTOR: Pre-flight snapshot succeeded: {stdout[:200]}")
            return True, stdout

        stderr: str = result.stderr.decode("utf-8", errors="replace").strip()
        stdout_err: str = result.stdout.decode("utf-8", errors="replace").strip()
        msg: str = (
            f"FATAL: Pre-flight snapshot failed (exit={result.returncode}). "
            f"stderr: {stderr[:500]} | stdout: {stdout_err[:500]}"
        )
        log.critical(msg)
        return False, msg

    except subprocess.TimeoutExpired:
        msg = (
            f"FATAL: Pre-flight snapshot timed out after "
            f"{SNAPSHOT_TIMEOUT_SECS}s. Intent execution blocked."
        )
        log.critical(msg)
        return False, msg

    except Exception as exc:
        msg = f"FATAL: Pre-flight snapshot raised {type(exc).__name__}: {exc}"
        log.critical(msg)
        return False, msg


# ── Intent Processing Pipeline ────────────────────────────────────────────────


def _process_intent(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Full intent processing pipeline:
      1. Schema validation (reject raw shell strings)
      2. Intent type validation (must be in _VALID_INTENTS)
      3. Target sanitization ([a-zA-Z0-9_.-] only)
      4. BTRFS pre-flight snapshot gate
      5. Command dispatch + execution

    Args:
        payload: Parsed JSON dict from the client.

    Returns:
        JSON-serializable response dict with status, message, and optional output.
    """
    t_start: float = time.monotonic()

    # ── Step 1: Schema validation ─────────────────────────────────────
    # Reject anything that isn't a proper intent structure.
    if not isinstance(payload, dict):
        return {
            "status": "REJECTED",
            "error": "Payload must be a JSON object.",
            "ts": time.time(),
        }

    intent: Any = payload.get("intent")
    target: Any = payload.get("target", "")

    if not isinstance(intent, str) or not intent:
        return {
            "status": "REJECTED",
            "error": "Missing or invalid 'intent' field. Must be a non-empty string.",
            "ts": time.time(),
        }

    # Reject raw shell strings masquerading as intents
    if any(c in intent for c in ("&", "|", ";", "$", "`", ">", "<", " ")):
        return {
            "status": "REJECTED",
            "error": "SECURITY: Intent field contains shell metacharacters. Raw shell strings are prohibited.",
            "ts": time.time(),
        }

    # ── Step 2: Intent type validation ────────────────────────────────
    if intent not in _VALID_INTENTS:
        return {
            "status": "REJECTED",
            "error": f"Unknown intent '{intent}'. Valid intents: {sorted(_VALID_INTENTS)}",
            "ts": time.time(),
        }

    # ── Step 3: Target sanitization ───────────────────────────────────
    if not isinstance(target, str):
        return {
            "status": "REJECTED",
            "error": "Target field must be a string.",
            "ts": time.time(),
        }

    if target:
        try:
            target = _validate_target(target)
        except ValueError as exc:
            return {
                "status": "REJECTED",
                "error": str(exc),
                "ts": time.time(),
            }

    # ── Step 4: BTRFS pre-flight snapshot gate ────────────────────────
    log.info(f"> EXECUTOR: Processing intent={intent} target={target}")
    log.info("> EXECUTOR: Triggering BTRFS pre-flight snapshot...")

    snap_ok, snap_msg = _execute_preflight_snapshot()
    if not snap_ok:
        log.critical(
            f"> EXECUTOR: Intent BLOCKED — snapshot pre-flight failed. "
            f"intent={intent} target={target}"
        )
        return {
            "status": "FATAL",
            "error": snap_msg,
            "intent": intent,
            "target": target,
            "ts": time.time(),
        }

    log.info("> EXECUTOR: Pre-flight snapshot gate PASSED.")

    # ── Step 5: Command dispatch ──────────────────────────────────────
    try:
        cmd, description = _build_command(intent, target)
    except ValueError as exc:
        return {
            "status": "REJECTED",
            "error": str(exc),
            "ts": time.time(),
        }

    log.info(f"> EXECUTOR: Dispatching — {description}")
    log.info(f"> EXECUTOR: Command: {cmd}")

    try:
        result: subprocess.CompletedProcess[bytes] = subprocess.run(
            cmd,
            capture_output=True,
            timeout=300,  # 5-minute hard deadline for system operations
            check=False,
        )

        elapsed: float = time.monotonic() - t_start
        stdout_text: str = result.stdout.decode("utf-8", errors="replace").strip()
        stderr_text: str = result.stderr.decode("utf-8", errors="replace").strip()

        if result.returncode == 0:
            log.info(
                f"> EXECUTOR: Intent {intent} SUCCEEDED "
                f"(exit=0, {elapsed:.2f}s)"
            )
            return {
                "status": "SUCCESS",
                "intent": intent,
                "target": target,
                "description": description,
                "exit_code": 0,
                "stdout": stdout_text[:4096],
                "stderr": stderr_text[:2048],
                "elapsed_secs": round(elapsed, 3),
                "ts": time.time(),
            }
        else:
            log.error(
                f"> EXECUTOR: Intent {intent} FAILED "
                f"(exit={result.returncode}, {elapsed:.2f}s)\n"
                f"  stderr: {stderr_text[:500]}"
            )
            return {
                "status": "FAILURE",
                "intent": intent,
                "target": target,
                "description": description,
                "exit_code": result.returncode,
                "stdout": stdout_text[:4096],
                "stderr": stderr_text[:2048],
                "elapsed_secs": round(elapsed, 3),
                "ts": time.time(),
            }

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t_start
        msg = f"Command timed out after 300s: {cmd}"
        log.error(f"> EXECUTOR: {msg}")
        return {
            "status": "TIMEOUT",
            "intent": intent,
            "target": target,
            "error": msg,
            "elapsed_secs": round(elapsed, 3),
            "ts": time.time(),
        }

    except Exception as exc:
        elapsed = time.monotonic() - t_start
        msg = f"{type(exc).__name__}: {exc}"
        log.error(f"> EXECUTOR: Unexpected error — {msg}")
        return {
            "status": "ERROR",
            "intent": intent,
            "target": target,
            "error": msg,
            "elapsed_secs": round(elapsed, 3),
            "ts": time.time(),
        }


# ── asyncio UDS Server ────────────────────────────────────────────────────────


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """
    Handle a single client connection on the UNIX domain socket.

    Protocol:
      1. Client sends a newline-terminated JSON payload.
      2. Server validates, gates with BTRFS snapshot, executes.
      3. Server responds with a newline-terminated JSON response.
      4. Connection is closed.

    One intent per connection. No persistent sessions.
    """
    peer: str = "unknown"
    try:
        peername: Any = writer.get_extra_info("peername")
        if peername:
            peer = str(peername)
    except Exception:
        pass

    log.info(f"> EXECUTOR: Client connected — {peer}")

    try:
        # Read payload with size limit to prevent memory exhaustion
        raw: bytes = await asyncio.wait_for(
            reader.readline(),
            timeout=10.0,
        )

        if not raw:
            log.warning(f"> EXECUTOR: Empty payload from {peer}")
            response: dict[str, Any] = {
                "status": "REJECTED",
                "error": "Empty payload.",
                "ts": time.time(),
            }
            writer.write(json.dumps(response).encode("utf-8") + b"\n")
            await writer.drain()
            return

        if len(raw) > MAX_PAYLOAD_BYTES:
            log.warning(
                f"> EXECUTOR: Payload too large from {peer} "
                f"({len(raw)} bytes, max={MAX_PAYLOAD_BYTES})"
            )
            response = {
                "status": "REJECTED",
                "error": f"Payload exceeds {MAX_PAYLOAD_BYTES} bytes.",
                "ts": time.time(),
            }
            writer.write(json.dumps(response).encode("utf-8") + b"\n")
            await writer.drain()
            return

        # ── Parse JSON — reject non-JSON payloads ─────────────────────
        try:
            payload: dict[str, Any] = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning(
                f"> EXECUTOR: Invalid JSON from {peer}: {exc}"
            )
            response = {
                "status": "REJECTED",
                "error": f"Invalid JSON: {exc}",
                "ts": time.time(),
            }
            writer.write(json.dumps(response).encode("utf-8") + b"\n")
            await writer.drain()
            return

        # ── Process the intent through the full pipeline ──────────────
        # Run in executor to avoid blocking the accept loop during
        # long-running subprocess calls (pacman -Syu, etc.)
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _process_intent, payload)

        writer.write(json.dumps(response).encode("utf-8") + b"\n")
        await writer.drain()

    except asyncio.TimeoutError:
        log.warning(f"> EXECUTOR: Client {peer} timed out reading payload.")
    except ConnectionResetError:
        log.warning(f"> EXECUTOR: Client {peer} disconnected.")
    except Exception as exc:
        log.error(f"> EXECUTOR: Error handling client {peer}: {exc}", exc_info=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        log.info(f"> EXECUTOR: Client disconnected — {peer}")


async def _run_server() -> None:
    """
    Bind the asyncio UNIX domain socket server and serve forever.

    Socket lifecycle:
      1. Remove stale socket file if present.
      2. Start asyncio.start_unix_server() on SOCKET_PATH.
      3. Set socket permissions to 0660 and ownership to root:yantra.
      4. Serve until SIGTERM/SIGINT.
    """
    # ── Clean up stale socket ─────────────────────────────────────────
    socket_path: Path = Path(SOCKET_PATH)
    if socket_path.exists():
        log.info(f"> EXECUTOR: Removing stale socket {SOCKET_PATH}")
        socket_path.unlink()

    # Ensure parent directory exists
    socket_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Start server ──────────────────────────────────────────────────
    server: asyncio.AbstractServer = await asyncio.start_unix_server(
        _handle_client,
        path=SOCKET_PATH,
    )

    # ── Set socket permissions ────────────────────────────────────────
    # root:yantra 0660 — only root and yantra group members can connect.
    os.chmod(SOCKET_PATH, SOCKET_MODE)
    try:
        yantra_gid: int = grp.getgrnam(SOCKET_GROUP).gr_gid
        os.chown(SOCKET_PATH, 0, yantra_gid)
        log.info(
            f"> EXECUTOR: Socket permissions set — "
            f"{SOCKET_PATH} root:{SOCKET_GROUP} {oct(SOCKET_MODE)}"
        )
    except KeyError:
        log.warning(
            f"> EXECUTOR: Group '{SOCKET_GROUP}' not found. "
            f"Socket ownership not changed — only root can connect."
        )
    except PermissionError as exc:
        log.error(f"> EXECUTOR: Failed to chown socket: {exc}")

    log.info(f"> EXECUTOR: Listening on {SOCKET_PATH}")
    log.info(f"> EXECUTOR: Valid intents: {sorted(_VALID_INTENTS)}")

    # ── Install signal handlers for graceful shutdown ──────────────────
    stop_event: asyncio.Event = asyncio.Event()

    def _signal_handler(signum: int, frame: Any) -> None:
        sig_name: str = signal.Signals(signum).name
        log.info(f"> EXECUTOR: Received {sig_name}. Shutting down...")
        stop_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # ── Serve until stop ──────────────────────────────────────────────
    async with server:
        await stop_event.wait()

    # ── Cleanup ───────────────────────────────────────────────────────
    log.info("> EXECUTOR: Server stopped. Cleaning up socket.")
    if socket_path.exists():
        socket_path.unlink()


# ── Entrypoint ────────────────────────────────────────────────────────────────


def main() -> None:
    """
    Configure logging and launch the host executor daemon.

    Exit codes:
      0 — Graceful shutdown (SIGTERM or SIGINT)
      1 — Fatal error during startup
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )

    log.info("> EXECUTOR: YantraOS Host Executor daemon starting...")
    log.info(f"> EXECUTOR: PID={os.getpid()} UID={os.getuid()} GID={os.getgid()}")

    if os.getuid() != 0:
        log.critical(
            "> EXECUTOR: FATAL — Must run as root. "
            "This daemon is the privilege boundary for the Kriya Loop."
        )
        sys.exit(1)

    try:
        asyncio.run(_run_server())
    except KeyboardInterrupt:
        log.info("> EXECUTOR: Interrupted (SIGINT). Exiting.")
        sys.exit(0)
    except Exception as exc:
        log.critical(f"> EXECUTOR: Fatal error: {exc}", exc_info=True)
        sys.exit(1)

    log.info("> EXECUTOR: Clean exit.")
    sys.exit(0)


if __name__ == "__main__":
    main()
