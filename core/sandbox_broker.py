"""Root broker exposing one fixed Docker-sandbox operation over a UDS."""

from __future__ import annotations

import asyncio
import grp
import json
import logging
import os
import pwd
import signal
import socket
import stat
import struct
from dataclasses import asdict
from typing import Any, Final

from .sandbox import (
    ExecOutcome,
    MAX_SCRIPT_BYTES,
    SandboxEngine,
    SandboxResult,
    SandboxStatus,
    sandbox,
    validate_script,
)

log = logging.getLogger("yantra.sandbox_broker")

BROKER_SOCKET_PATH: Final[str] = "/run/yantra-sandbox/broker.sock"
AUTHORIZED_USER: Final[str] = "yantra_daemon"
SOCKET_GROUP: Final[str] = "yantra"
MAX_REQUEST_BYTES: Final[int] = (MAX_SCRIPT_BYTES * 6) + 64
REQUEST_TIMEOUT_SECS: Final[int] = 5
_PEERCRED_SIZE: Final[int] = struct.calcsize("3i")


class RequestError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RequestError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _peer_credentials(writer: Any) -> tuple[int, int, int]:
    peer_socket = writer.get_extra_info("socket")
    if peer_socket is None:
        raise RequestError("peer socket is unavailable")
    credentials = peer_socket.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED_SIZE
    )
    if len(credentials) != _PEERCRED_SIZE:
        raise RequestError("invalid peer credentials")
    return struct.unpack("3i", credentials)


async def _read_bounded_request(reader: Any) -> bytes:
    try:
        data = await asyncio.wait_for(
            reader.readexactly(MAX_REQUEST_BYTES + 1),
            timeout=REQUEST_TIMEOUT_SECS,
        )
    except asyncio.IncompleteReadError as exc:
        data = exc.partial
    if len(data) > MAX_REQUEST_BYTES:
        raise RequestError("request exceeds the wire-size limit")
    return data


def _decode_request(data: bytes) -> str:
    if not data.endswith(b"\n") or data.count(b"\n") != 1:
        raise RequestError("request must be exactly one newline-terminated object")
    try:
        payload = json.loads(
            data[:-1].decode("utf-8"), object_pairs_hook=_unique_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RequestError) as exc:
        raise RequestError("request is not valid UTF-8 JSON") from exc
    if type(payload) is not dict or set(payload) != {"script"}:
        raise RequestError("request must contain only the script field")
    try:
        return validate_script(payload["script"])
    except (TypeError, ValueError) as exc:
        raise RequestError(str(exc)) from exc


def _error_result(outcome: ExecOutcome, message: str) -> SandboxResult:
    return SandboxResult(outcome=outcome, error=message)


async def _write_result(writer: Any, result: SandboxResult) -> None:
    payload = asdict(result)
    payload["outcome"] = result.outcome.value
    writer.write(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        + b"\n"
    )
    await writer.drain()


async def _close_writer(writer: Any) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


class SandboxBroker:
    def __init__(self, backend: SandboxEngine = sandbox) -> None:
        # Name resolution is mandatory: there is no UID range or group-only
        # authorization fallback.
        self._authorized_uid = pwd.getpwnam(AUTHORIZED_USER).pw_uid
        self._socket_gid = grp.getgrnam(SOCKET_GROUP).gr_gid
        self._sandbox = backend
        self._server: asyncio.AbstractServer | None = None

    async def _handle_client(self, reader: Any, writer: Any) -> None:
        try:
            pid, uid, _gid = _peer_credentials(writer)
            if uid != self._authorized_uid:
                log.warning(
                    "Rejected sandbox broker peer pid=%d uid=%d", pid, uid
                )
                return

            data = await _read_bounded_request(reader)
            # initialize() probes ownership and peer credentials without
            # submitting an operation.
            if not data:
                return
            try:
                script = _decode_request(data)
            except RequestError as exc:
                await _write_result(
                    writer,
                    _error_result(ExecOutcome.VALIDATION_ERROR, str(exc)),
                )
                return

            result = await self._sandbox.execute(script)
            await _write_result(writer, result)
        except (RequestError, asyncio.TimeoutError) as exc:
            log.warning("Rejected malformed sandbox request: %s", exc)
            try:
                await _write_result(
                    writer,
                    _error_result(ExecOutcome.VALIDATION_ERROR, str(exc)),
                )
            except Exception:
                pass
        except Exception as exc:
            log.exception("Sandbox broker request failed")
            try:
                await _write_result(
                    writer,
                    _error_result(ExecOutcome.DOCKER_ERROR, str(exc)),
                )
            except Exception:
                pass
        finally:
            await _close_writer(writer)

    async def start(self) -> None:
        status = await self._sandbox.initialize()
        if status != SandboxStatus.HEALTHY:
            raise RuntimeError(f"sandbox backend failed to initialize: {status.value}")
        await self._sandbox.cleanup_stale_containers()
        if not self._sandbox.is_operational:
            raise RuntimeError("stale sandbox container cleanup failed")

        try:
            existing = os.lstat(BROKER_SOCKET_PATH)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(existing.st_mode):
                raise RuntimeError("broker socket path exists and is not a socket")
            os.unlink(BROKER_SOCKET_PATH)

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=BROKER_SOCKET_PATH,
            limit=MAX_REQUEST_BYTES + 1,
        )
        os.chown(BROKER_SOCKET_PATH, 0, self._socket_gid)
        os.chmod(BROKER_SOCKET_PATH, 0o660)
        socket_info = os.stat(BROKER_SOCKET_PATH, follow_symlinks=False)
        if (
            socket_info.st_uid != 0
            or socket_info.st_gid != self._socket_gid
            or stat.S_IMODE(socket_info.st_mode) != 0o660
        ):
            raise RuntimeError("broker socket ownership or mode verification failed")
        log.info("Sandbox broker listening on %s", BROKER_SOCKET_PATH)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        try:
            existing = os.lstat(BROKER_SOCKET_PATH)
            if stat.S_ISSOCK(existing.st_mode):
                os.unlink(BROKER_SOCKET_PATH)
        except FileNotFoundError:
            pass
        self._sandbox.shutdown()


async def _run() -> None:
    broker = SandboxBroker()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    try:
        await broker.start()
        await stop.wait()
    finally:
        await broker.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
