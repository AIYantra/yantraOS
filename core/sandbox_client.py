"""Unprivileged, authenticated client for the YantraOS sandbox broker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
import stat
import struct
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

log = logging.getLogger("yantra.sandbox_client")

BROKER_SOCKET_PATH: Final[str] = "/run/yantra-sandbox/broker.sock"
MAX_SCRIPT_BYTES: Final[int] = 65_536
MAX_REQUEST_BYTES: Final[int] = (MAX_SCRIPT_BYTES * 6) + 64
# JSON escaping can expand each bounded output byte to a six-byte escape.
MAX_RESPONSE_BYTES: Final[int] = (12 * 1_048_576) + 65_536
BROKER_RESPONSE_TIMEOUT_SECS: Final[int] = 25
SANDBOX_IMAGE: Final[str] = "yantra-sandbox:3.20.3"
_PEERCRED_SIZE: Final[int] = struct.calcsize("3i")


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


class BrokerSecurityError(ConnectionError):
    pass


def _validate_script(script: str) -> str:
    if not isinstance(script, str):
        raise ValueError("script must be a string")
    if not script.strip():
        raise ValueError("script must not be empty")
    if "\x00" in script:
        raise ValueError("script must not contain NUL bytes")
    if len(script.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise ValueError(f"script exceeds the {MAX_SCRIPT_BYTES}-byte limit")
    return script


def _root_peer_uid(sock: Any) -> int:
    credentials = sock.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED_SIZE
    )
    if len(credentials) != _PEERCRED_SIZE:
        raise BrokerSecurityError("invalid broker peer credentials")
    _pid, uid, _gid = struct.unpack("3i", credentials)
    return uid


async def _close_writer(writer: Any) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


def _result_from_response(payload: Any) -> SandboxResult:
    if not isinstance(payload, dict):
        raise ValueError("broker response must be a JSON object")
    try:
        outcome = ExecOutcome(payload["outcome"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("broker response has an invalid outcome") from exc

    exit_code = payload.get("exit_code", -1)
    duration = payload.get("duration_secs", 0.0)
    error = payload.get("error")
    string_fields = {
        name: payload.get(name, "")
        for name in ("stdout", "stderr", "container_id", "script_hash")
    }
    if type(exit_code) is not int:
        raise ValueError("broker response has an invalid exit code")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValueError("broker response has an invalid duration")
    if any(not isinstance(value, str) for value in string_fields.values()):
        raise ValueError("broker response has an invalid string field")
    if error is not None and not isinstance(error, str):
        raise ValueError("broker response has an invalid error field")
    if payload.get("image", SANDBOX_IMAGE) != SANDBOX_IMAGE:
        raise BrokerSecurityError("broker reported an unexpected runtime image")

    return SandboxResult(
        outcome=outcome,
        exit_code=exit_code,
        stdout=string_fields["stdout"],
        stderr=string_fields["stderr"],
        duration_secs=float(duration),
        container_id=string_fields["container_id"],
        image=SANDBOX_IMAGE,
        script_hash=string_fields["script_hash"],
        error=error,
    )


class SandboxClient:
    def __init__(self, socket_path: str = BROKER_SOCKET_PATH) -> None:
        self._socket_path = socket_path
        self._status = SandboxStatus.UNAVAILABLE

    @property
    def status(self) -> SandboxStatus:
        return self._status

    @property
    def is_operational(self) -> bool:
        return self._status == SandboxStatus.HEALTHY

    async def _open_verified(self) -> tuple[Any, Any]:
        socket_info = os.stat(self._socket_path, follow_symlinks=False)
        if not stat.S_ISSOCK(socket_info.st_mode):
            raise BrokerSecurityError("sandbox broker path is not a socket")
        if socket_info.st_uid != 0:
            raise BrokerSecurityError("sandbox broker socket is not root-owned")

        reader, writer = await asyncio.open_unix_connection(
            path=self._socket_path,
            limit=MAX_RESPONSE_BYTES + 1,
        )
        try:
            peer_socket = writer.get_extra_info("socket")
            if peer_socket is None or _root_peer_uid(peer_socket) != 0:
                raise BrokerSecurityError("sandbox broker peer is not root")
        except Exception:
            await _close_writer(writer)
            raise
        return reader, writer

    async def initialize(self) -> SandboxStatus:
        try:
            _reader, writer = await self._open_verified()
            await _close_writer(writer)
        except Exception as exc:
            self._status = SandboxStatus.DEGRADED
            log.error("Sandbox broker verification failed: %s", exc)
        else:
            self._status = SandboxStatus.HEALTHY
        return self._status

    async def execute(self, script: str) -> SandboxResult:
        script_hash = ""
        try:
            script = _validate_script(script)
            script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()[:16]
        except ValueError as exc:
            return SandboxResult(
                outcome=ExecOutcome.VALIDATION_ERROR,
                script_hash=script_hash,
                error=str(exc),
            )

        writer: Any = None
        try:
            reader, writer = await self._open_verified()
            request = json.dumps(
                {"script": script}, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8") + b"\n"
            if len(request) > MAX_REQUEST_BYTES:
                raise ValueError("encoded sandbox request is too large")
            writer.write(request)
            await writer.drain()
            if not writer.can_write_eof():
                raise BrokerSecurityError("broker socket cannot enforce request EOF")
            writer.write_eof()

            response = await asyncio.wait_for(
                reader.readline(), timeout=BROKER_RESPONSE_TIMEOUT_SECS
            )
            if not response or not response.endswith(b"\n"):
                raise ConnectionError("sandbox broker returned an incomplete response")
            if len(response) > MAX_RESPONSE_BYTES:
                raise ConnectionError("sandbox broker response is too large")
            result = _result_from_response(json.loads(response.decode("utf-8")))
            self._status = (
                SandboxStatus.DEGRADED
                if result.outcome == ExecOutcome.DOCKER_ERROR
                else SandboxStatus.HEALTHY
            )
            return result
        except Exception as exc:
            self._status = SandboxStatus.DEGRADED
            log.error("Sandbox broker request failed: %s", exc)
            return SandboxResult(
                outcome=ExecOutcome.DOCKER_ERROR,
                script_hash=script_hash,
                error=f"sandbox broker unavailable: {exc}",
            )
        finally:
            if writer is not None:
                await _close_writer(writer)

    async def cleanup_stale_containers(self) -> int:
        # The client has no Docker-control RPC. The broker cleans stale labeled
        # containers at startup and force-removes every execution in finally.
        return 0

    def shutdown(self) -> None:
        self._status = SandboxStatus.UNAVAILABLE


sandbox = SandboxClient()
