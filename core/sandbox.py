"""Root-only Docker backend for the YantraOS sandbox broker."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import Any, Final

log = logging.getLogger("yantra.sandbox")

# These settings are the broker's fixed security policy. No request field can
# alter them.
SANDBOX_IMAGE: Final[str] = "yantra-sandbox:3.20.3"
EXECUTION_TIMEOUT_SECS: Final[int] = 10
DOCKER_API_TIMEOUT_SECS: Final[int] = 5
MAX_SCRIPT_BYTES: Final[int] = 65_536
MAX_OUTPUT_BYTES: Final[int] = 1_048_576
CONTAINER_MEM_LIMIT: Final[str] = "512m"
CONTAINER_CPU_PERIOD: Final[int] = 100_000
CONTAINER_CPU_QUOTA: Final[int] = 50_000
CONTAINER_TMPFS_SIZE: Final[str] = "64m"
CONTAINER_PIDS_LIMIT: Final[int] = 64
CONTAINER_LABEL: Final[str] = "yantra=sandbox"
POLL_INTERVAL_SECS: Final[float] = 0.05


class SandboxStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class ExecOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    DOCKER_ERROR = "docker_error"
    VALIDATION_ERROR = "validation_error"


@dataclass(frozen=True, slots=True)
class SandboxResult:
    outcome: ExecOutcome
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    duration_secs: float = 0.0
    container_id: str = ""
    image: str = SANDBOX_IMAGE
    script_hash: str = ""
    error: str | None = None


class InputValidationError(ValueError):
    pass


def validate_script(script: str) -> str:
    if not isinstance(script, str):
        raise InputValidationError("script must be a string")
    if not script.strip():
        raise InputValidationError("script must not be empty")
    if "\x00" in script:
        raise InputValidationError("script must not contain NUL bytes")
    size = len(script.encode("utf-8"))
    if size > MAX_SCRIPT_BYTES:
        raise InputValidationError(
            f"script exceeds the {MAX_SCRIPT_BYTES}-byte limit"
        )
    return script


def _decode_capped(data: bytes) -> str:
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        text = encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
    return text


def _read_capped_logs(container: Any, *, stdout: bool, stderr: bool) -> str:
    chunks: list[bytes] = []
    total = 0
    stream: Any = None
    try:
        stream = container.logs(
            stream=True,
            follow=False,
            stdout=stdout,
            stderr=stderr,
        )
        iterable = [stream] if isinstance(stream, (bytes, bytearray)) else stream
        for chunk in iterable:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="replace")
            elif not isinstance(chunk, (bytes, bytearray)):
                chunk = bytes(chunk)
            remaining = MAX_OUTPUT_BYTES - total
            if remaining <= 0:
                break
            piece = bytes(chunk[:remaining])
            chunks.append(piece)
            total += len(piece)
            if len(chunk) > remaining:
                break
    except Exception as exc:
        raise RuntimeError("Sandbox log read failed") from exc
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return _decode_capped(b"".join(chunks))


class SandboxEngine:
    """Blocking Docker access isolated behind the root broker process."""

    __slots__ = (
        "_client",
        "_docker",
        "_status",
        "_executor",
        "_closed",
        "_active_containers",
        "_active_lock",
    )

    def __init__(self) -> None:
        self._client: Any = None
        self._docker: Any = None
        self._status = SandboxStatus.UNAVAILABLE
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="yantra-sandbox"
        )
        self._closed = False
        self._active_containers: dict[str, Any] = {}
        self._active_lock = threading.Lock()

    @property
    def status(self) -> SandboxStatus:
        return self._status

    @property
    def is_operational(self) -> bool:
        return self._status == SandboxStatus.HEALTHY and self._client is not None

    async def initialize(self) -> SandboxStatus:
        if self._closed:
            self._status = SandboxStatus.UNAVAILABLE
            return self._status
        loop = asyncio.get_running_loop()
        self._status = await loop.run_in_executor(
            self._executor, self._blocking_initialize
        )
        return self._status

    def _blocking_initialize(self) -> SandboxStatus:
        if os.geteuid() != 0:
            log.critical("Docker sandbox backend refuses to run outside root broker")
            return SandboxStatus.UNAVAILABLE
        try:
            import docker  # type: ignore[import-untyped]
        except ImportError:
            log.error("Docker SDK is unavailable; sandbox broker cannot start")
            return SandboxStatus.UNAVAILABLE

        client: Any = None
        try:
            client = docker.from_env(timeout=DOCKER_API_TIMEOUT_SECS)
            client.ping()
            # Fail closed if the pinned image was not provisioned. The broker
            # never pulls or builds a mutable image at runtime.
            client.images.get(SANDBOX_IMAGE)
        except Exception as exc:
            log.error("Docker sandbox initialization failed: %s", exc)
            try:
                if client is not None:
                    client.close()
            except Exception:
                pass
            self._client = None
            return SandboxStatus.DEGRADED

        self._docker = docker
        self._client = client
        log.info("Docker sandbox ready with pinned runtime %s", SANDBOX_IMAGE)
        return SandboxStatus.HEALTHY

    async def execute(self, script: str) -> SandboxResult:
        script_hash = ""
        try:
            script = validate_script(script)
            script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()[:16]
        except InputValidationError as exc:
            return SandboxResult(
                outcome=ExecOutcome.VALIDATION_ERROR,
                script_hash=script_hash,
                error=str(exc),
            )

        if not self.is_operational:
            return SandboxResult(
                outcome=ExecOutcome.DOCKER_ERROR,
                script_hash=script_hash,
                error=f"sandbox backend is {self._status.value}",
            )

        loop = asyncio.get_running_loop()
        active_key = f"{script_hash}:{secrets.token_hex(8)}"
        run = partial(self._blocking_execute, script, script_hash, active_key)
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self._executor, run),
                timeout=EXECUTION_TIMEOUT_SECS + (4 * DOCKER_API_TIMEOUT_SECS),
            )
        except asyncio.TimeoutError:
            self._status = SandboxStatus.DEGRADED
            log.error("Docker API stalled while executing script %s", script_hash)
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._force_remove_active, active_key),
                    timeout=DOCKER_API_TIMEOUT_SECS + 1,
                )
            except Exception as cleanup_exc:
                log.error("Independent timeout cleanup failed: %s", cleanup_exc)
            return SandboxResult(
                outcome=ExecOutcome.TIMEOUT,
                script_hash=script_hash,
                error="Docker API exceeded the fixed execution deadline",
            )

    def _blocking_execute(
        self, script: str, script_hash: str, active_key: str | None = None
    ) -> SandboxResult:
        active_key = active_key or script_hash
        started = time.monotonic()
        container: Any = None
        container_id = ""
        result: SandboxResult | None = None
        cleanup_error: str | None = None

        try:
            log_config = self._docker.types.LogConfig(
                type="json-file",
                config={"max-size": "1m", "max-file": "1"},
            )
            # create() plus start() is detached execution and preserves the ID
            # needed for unconditional cleanup.
            container = self._client.containers.create(
                image=SANDBOX_IMAGE,
                command=["/bin/sh", "-c", script],
                network_mode="none",
                mem_limit=CONTAINER_MEM_LIMIT,
                cpu_period=CONTAINER_CPU_PERIOD,
                cpu_quota=CONTAINER_CPU_QUOTA,
                pids_limit=CONTAINER_PIDS_LIMIT,
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                auto_remove=False,
                tmpfs={
                    "/tmp": (
                        f"size={CONTAINER_TMPFS_SIZE},noexec,nosuid,nodev"
                    )
                },
                user="nobody",
                privileged=False,
                stdin_open=False,
                tty=False,
                stop_signal="SIGKILL",
                labels={"yantra": "sandbox", "script_hash": script_hash},
                log_config=log_config,
            )
            container_id = str(container.id)
            with self._active_lock:
                self._active_containers[active_key] = container
            container.start()

            deadline = started + EXECUTION_TIMEOUT_SECS
            timed_out = False
            exit_code = -1
            while True:
                container.reload()
                if container.status in {"exited", "dead"}:
                    state = container.attrs.get("State", {})
                    exit_code = int(state.get("ExitCode", -1))
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                time.sleep(min(POLL_INTERVAL_SECS, remaining))

            if timed_out:
                try:
                    container.kill()
                except Exception as exc:
                    log.warning("Timed-out container kill failed: %s", exc)

            stdout = _read_capped_logs(container, stdout=True, stderr=False)
            stderr = _read_capped_logs(container, stdout=False, stderr=True)
            elapsed = round(time.monotonic() - started, 3)

            if timed_out:
                result = SandboxResult(
                    outcome=ExecOutcome.TIMEOUT,
                    stdout=stdout,
                    stderr=stderr,
                    duration_secs=elapsed,
                    container_id=container_id,
                    script_hash=script_hash,
                    error=(
                        f"execution exceeded {EXECUTION_TIMEOUT_SECS}s deadline"
                    ),
                )
            else:
                result = SandboxResult(
                    outcome=(
                        ExecOutcome.SUCCESS
                        if exit_code == 0
                        else ExecOutcome.FAILURE
                    ),
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    duration_secs=elapsed,
                    container_id=container_id,
                    script_hash=script_hash,
                )
        except Exception as exc:
            self._status = SandboxStatus.DEGRADED
            log.error("Sandbox execution failed for %s: %s", script_hash, exc)
            result = SandboxResult(
                outcome=ExecOutcome.DOCKER_ERROR,
                duration_secs=round(time.monotonic() - started, 3),
                container_id=container_id,
                script_hash=script_hash,
                error=str(exc),
            )
        finally:
            with self._active_lock:
                self._active_containers.pop(active_key, None)
            if container is not None:
                try:
                    container.kill()
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                except Exception as exc:
                    cleanup_error = str(exc)
                    self._status = SandboxStatus.DEGRADED
                    log.error(
                        "Force-removal failed for sandbox container %s: %s",
                        container_id,
                        exc,
                    )

        if cleanup_error is not None:
            return SandboxResult(
                outcome=ExecOutcome.DOCKER_ERROR,
                stdout=result.stdout if result is not None else "",
                stderr=result.stderr if result is not None else "",
                duration_secs=round(time.monotonic() - started, 3),
                container_id=container_id,
                script_hash=script_hash,
                error=f"container cleanup failed: {cleanup_error}",
            )
        if result is None:
            self._status = SandboxStatus.DEGRADED
            return SandboxResult(
                outcome=ExecOutcome.DOCKER_ERROR,
                container_id=container_id,
                script_hash=script_hash,
                error="sandbox execution produced no result",
            )
        return result

    def _force_remove_active(self, active_key: str) -> None:
        with self._active_lock:
            container = self._active_containers.get(active_key)
        if container is None:
            return
        try:
            container.kill()
        except Exception:
            pass
        container.remove(force=True)

    async def cleanup_stale_containers(self) -> int:
        if not self.is_operational:
            return 0
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, self._blocking_cleanup_stale_containers
        )

    def _blocking_cleanup_stale_containers(self) -> int:
        removed = 0
        try:
            containers = self._client.containers.list(
                all=True, filters={"label": [CONTAINER_LABEL]}
            )
        except Exception as exc:
            self._status = SandboxStatus.DEGRADED
            log.error("Unable to list stale sandbox containers: %s", exc)
            return 0

        for container in containers:
            try:
                container.kill()
            except Exception:
                pass
            try:
                container.remove(force=True)
                removed += 1
            except Exception as exc:
                self._status = SandboxStatus.DEGRADED
                log.error("Unable to remove stale sandbox container: %s", exc)
        if removed:
            log.warning("Force-removed %d stale sandbox container(s)", removed)
        return removed

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._status = SandboxStatus.UNAVAILABLE
        self._executor.shutdown(wait=True)
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None


sandbox = SandboxEngine()
