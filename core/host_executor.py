"""Root-only executor for a small set of typed YantraOS host intents."""

from __future__ import annotations

import asyncio
import grp
import json
import logging
import os
import pwd
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import audit_log

log = logging.getLogger("yantra.host_executor")

SOCKET_PATH = "/run/yantra/executor.sock"
SOCKET_MODE = 0o660
SOCKET_DIRECTORY_MODE = 0o750
SOCKET_GROUP = "yantra"
AUTHORIZED_USER = "yantra_daemon"

SNAPSHOT_BIN = "/usr/bin/yantra-snapshot"
SNAPSHOT_TIMEOUT_SECS = 60
COMMAND_TIMEOUT_SECS = 300
MAX_PAYLOAD_BYTES = 16_384
MAX_RESPONSE_BYTES = 16_384
MAX_STDOUT_BYTES = 4_096
MAX_STDERR_BYTES = 2_048

_SAFE_TARGET_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
_SYSTEMD_INTENTS = frozenset({"RESTART_DAEMON"})
_TARGET_REQUIRED_INTENTS = _SYSTEMD_INTENTS
_TARGET_FORBIDDEN_INTENTS: frozenset[str] = frozenset()
_ALLOWED_SYSTEMD_UNITS = frozenset({"yantra.service"})
_VALID_INTENTS = _TARGET_REQUIRED_INTENTS | _TARGET_FORBIDDEN_INTENTS

_SAFE_LIVE_INTENTS = frozenset({"RESTART_DAEMON"})
_DESTRUCTIVE_INTENTS: frozenset[str] = frozenset()

# Snapshot creation and the mutation it protects are one indivisible operation.
_operation_lock = threading.Lock()


def _is_live_iso() -> bool:
    return Path("/run/archiso/cowspace").exists()


def _resolve_socket_group() -> int:
    """Resolve only the configured Yantra group; never infer it from the process."""
    try:
        group = grp.getgrnam(SOCKET_GROUP)
    except KeyError as exc:
        raise RuntimeError(f"Required group '{SOCKET_GROUP}' does not exist.") from exc
    return group.gr_gid


def _resolve_authorized_uid() -> int:
    """Return the sole UID allowed to submit privileged host intents."""
    try:
        account = pwd.getpwnam(AUTHORIZED_USER)
    except KeyError as exc:
        raise RuntimeError(f"Required user '{AUTHORIZED_USER}' does not exist.") from exc
    if account.pw_uid == 0:
        raise RuntimeError(f"Authorized user '{AUTHORIZED_USER}' must not be root.")
    return account.pw_uid


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _verify_socket_metadata(metadata: os.stat_result, expected_gid: int) -> None:
    if not stat.S_ISSOCK(metadata.st_mode):
        raise RuntimeError("Executor socket path is not a UNIX socket.")
    if metadata.st_uid != 0 or metadata.st_gid != expected_gid:
        raise RuntimeError("Executor socket must be owned by root:yantra.")
    if stat.S_IMODE(metadata.st_mode) != SOCKET_MODE:
        raise RuntimeError(
            f"Executor socket mode is {oct(stat.S_IMODE(metadata.st_mode))}, "
            f"expected {oct(SOCKET_MODE)}."
        )


def _configure_socket_permissions(socket_path: str, socket_gid: int | None = None) -> None:
    """Verify bind-time ownership without following or modifying the path."""
    expected_gid = _resolve_socket_group() if socket_gid is None else socket_gid
    path = Path(socket_path)
    directory_fd = os.open(path.parent, _directory_flags())
    try:
        metadata = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        _verify_socket_metadata(metadata, expected_gid)
    finally:
        os.close(directory_fd)


def _create_listening_socket(socket_path: str = SOCKET_PATH) -> socket.socket:
    """Bind a root:yantra socket atomically under a secured runtime directory."""
    if os.geteuid() != 0:
        raise RuntimeError("Executor socket creation requires root.")

    socket_gid = _resolve_socket_group()
    path = Path(socket_path)
    parent = path.parent
    grandparent_fd = os.open(parent.parent, _directory_flags())
    try:
        try:
            os.mkdir(parent.name, SOCKET_DIRECTORY_MODE, dir_fd=grandparent_fd)
        except FileExistsError:
            pass
        directory_fd = os.open(parent.name, _directory_flags(), dir_fd=grandparent_fd)
    finally:
        os.close(grandparent_fd)

    listener: socket.socket | None = None
    created = False
    try:
        directory_metadata = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_metadata.st_mode) or directory_metadata.st_uid != 0:
            raise RuntimeError("Executor socket directory must be a root-owned directory.")
        os.fchown(directory_fd, 0, socket_gid)
        os.fchmod(directory_fd, SOCKET_DIRECTORY_MODE)

        try:
            stale = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(stale.st_mode) or stale.st_uid != 0:
                raise RuntimeError("Refusing to replace an unsafe executor socket path.")
            os.unlink(path.name, dir_fd=directory_fd)

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.set_inheritable(False)

        old_egid = os.getegid()
        old_umask = os.umask(0o117)
        try:
            os.setegid(socket_gid)
            listener.bind(socket_path)
            created = True
        finally:
            os.setegid(old_egid)
            os.umask(old_umask)

        metadata = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        _verify_socket_metadata(metadata, socket_gid)
        listener.listen(socket.SOMAXCONN)
        listener.setblocking(False)
        return listener
    except Exception:
        if listener is not None:
            listener.close()
        if created:
            try:
                metadata = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0:
                    os.unlink(path.name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(directory_fd)


def _unlink_socket(socket_path: str = SOCKET_PATH) -> None:
    """Remove only the root-owned socket entry, never a replacement path."""
    path = Path(socket_path)
    try:
        directory_fd = os.open(path.parent, _directory_flags())
    except FileNotFoundError:
        return
    try:
        try:
            metadata = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == 0:
            os.unlink(path.name, dir_fd=directory_fd)
        else:
            log.error("Refusing to unlink a replacement at %s", socket_path)
    finally:
        os.close(directory_fd)


def _peer_credentials(writer: asyncio.StreamWriter) -> tuple[int, int, int]:
    peer_socket = writer.get_extra_info("socket")
    peer_cred = getattr(socket, "SO_PEERCRED", None)
    if peer_socket is None or peer_cred is None:
        raise PermissionError("UNIX peer credential verification is unavailable.")
    try:
        raw = peer_socket.getsockopt(
            socket.SOL_SOCKET, peer_cred, struct.calcsize("3i")
        )
        pid, uid, gid = struct.unpack("3i", raw)
    except (OSError, struct.error) as exc:
        raise PermissionError("Could not verify UNIX peer credentials.") from exc
    if pid <= 0 or uid < 0 or gid < 0:
        raise PermissionError("UNIX peer credentials are invalid.")
    return pid, uid, gid


def _validate_target(target: str) -> str:
    if not target:
        raise ValueError("Intent target cannot be empty.")
    if len(target) > 128 or not _SAFE_TARGET_RE.fullmatch(target):
        raise ValueError("Intent target contains disallowed characters.")
    return target


def _validate_intent_target(intent: str, target: Any) -> str:
    if not isinstance(target, str):
        raise ValueError("Target field must be a string.")

    if intent in _TARGET_FORBIDDEN_INTENTS:
        if target:
            raise ValueError(f"Intent '{intent}' forbids a target.")
        return ""

    if intent in _SYSTEMD_INTENTS:
        target = _validate_target(target)
        if target not in _ALLOWED_SYSTEMD_UNITS:
            raise ValueError(
                f"Systemd target '{target}' is not an allowed Yantra unit."
            )
        return target

    raise ValueError(f"Unknown intent '{intent}'.")


def _build_command(intent: str, target: str) -> tuple[list[str], str]:
    target = _validate_intent_target(intent, target)
    dispatch: dict[str, tuple[list[str], str]] = {
        "RESTART_DAEMON": (
            ["/usr/bin/systemctl", "restart", target],
            f"Restart systemd unit: {target}",
        ),
    }
    return dispatch[intent]


def _bounded_output(value: bytes | str | None, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value[:limit].decode("utf-8", errors="replace").strip()
    return value[:limit].strip()


def _run_bounded_command(
    command: list[str], timeout: int, stdout_limit: int, stderr_limit: int
) -> subprocess.CompletedProcess[bytes]:
    """Drain child pipes fully while retaining only bounded prefixes."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    captured: dict[str, bytearray] = {
        "stdout": bytearray(),
        "stderr": bytearray(),
    }

    def drain(name: str, pipe: Any, limit: int) -> None:
        while True:
            chunk = pipe.read(8192)
            if not chunk:
                return
            remaining = limit - len(captured[name])
            if remaining > 0:
                captured[name].extend(chunk[:remaining])

    threads = [
        threading.Thread(
            target=drain,
            args=("stdout", process.stdout, stdout_limit),
            daemon=True,
        ),
        threading.Thread(
            target=drain,
            args=("stderr", process.stderr, stderr_limit),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        for thread in threads:
            thread.join(timeout=2)
        process.stdout.close()
        process.stderr.close()
        raise
    for thread in threads:
        thread.join(timeout=2)
        if thread.is_alive():
            process.kill()
            process.stdout.close()
            process.stderr.close()
            raise RuntimeError("Bounded command output reader did not terminate")
    process.stdout.close()
    process.stderr.close()
    return subprocess.CompletedProcess(
        command,
        returncode,
        bytes(captured["stdout"]),
        bytes(captured["stderr"]),
    )


def _execute_preflight_snapshot() -> tuple[bool, str]:
    if Path(SNAPSHOT_BIN).is_file() and os.access(SNAPSHOT_BIN, os.X_OK):
        command = [SNAPSHOT_BIN, "--pre-flight"]
    else:
        snapshot_module = Path(__file__).parent / "cli_snapshot.py"
        if not snapshot_module.is_file():
            message = (
                f"FATAL: Snapshot wrapper missing at {SNAPSHOT_BIN} and "
                f"snapshot module missing at {snapshot_module}. Mutation blocked."
            )
            log.critical(message)
            return False, message
        command = [sys.executable, "-m", "core.cli_snapshot", "--pre-flight"]
        log.warning("Snapshot wrapper missing; using packaged snapshot module.")

    try:
        result = _run_bounded_command(
            command,
            SNAPSHOT_TIMEOUT_SECS,
            500,
            500,
        )
    except subprocess.TimeoutExpired:
        message = (
            f"FATAL: Pre-flight snapshot timed out after {SNAPSHOT_TIMEOUT_SECS}s. "
            "Intent execution blocked."
        )
        log.critical(message)
        return False, message
    except Exception as exc:
        message = f"FATAL: Pre-flight snapshot raised {type(exc).__name__}: {exc}"
        log.critical(message)
        return False, message[:MAX_STDERR_BYTES]

    stdout = _bounded_output(result.stdout, 500)
    stderr = _bounded_output(result.stderr, 500)
    if result.returncode == 0:
        log.info("Pre-flight snapshot succeeded: %s", stdout)
        return True, stdout

    message = (
        f"FATAL: Pre-flight snapshot failed (exit={result.returncode}). "
        f"stderr: {stderr} | stdout: {stdout}"
    )
    log.critical(message)
    return False, message[:MAX_STDERR_BYTES]


def _response(status: str, **fields: Any) -> dict[str, Any]:
    return {"status": status, **fields, "ts": time.time()}


def _execute_locked_intent(intent: str, target: str, started: float) -> dict[str, Any]:
    if not audit_log.log_action(
        phase="PROPOSED",
        action={"action": intent, "target": target},
    ):
        return _response(
            "FATAL", intent=intent, target=target, error="Privileged audit unavailable."
        )
    if _is_live_iso():
        if intent in _DESTRUCTIVE_INTENTS:
            message = (
                f"Live ISO overlayfs detected. Destructive intent '{intent}' "
                "is blocked on ephemeral sessions."
            )
            return _response("BLOCKED", intent=intent, target=target, error=message)
        if intent not in _SAFE_LIVE_INTENTS:
            return _response("REJECTED", intent=intent, error="Intent is not allowed on Live ISO.")
    else:
        snapshot_ok, snapshot_message = _execute_preflight_snapshot()
        if not snapshot_ok:
            return _response(
                "FATAL",
                intent=intent,
                target=target,
                error=snapshot_message[:MAX_STDERR_BYTES],
            )

    cmd, description = _build_command(intent, target)
    log.info("Dispatching %s", description)
    try:
        result = _run_bounded_command(
            cmd,
            COMMAND_TIMEOUT_SECS,
            MAX_STDOUT_BYTES,
            MAX_STDERR_BYTES,
        )
    except subprocess.TimeoutExpired:
        return _response(
            "TIMEOUT",
            intent=intent,
            target=target,
            error=f"Command timed out after {COMMAND_TIMEOUT_SECS}s.",
            elapsed_secs=round(time.monotonic() - started, 3),
        )
    except Exception as exc:
        return _response(
            "ERROR",
            intent=intent,
            target=target,
            error=f"{type(exc).__name__}: {exc}"[:MAX_STDERR_BYTES],
            elapsed_secs=round(time.monotonic() - started, 3),
        )

    status = "SUCCESS" if result.returncode == 0 else "FAILURE"
    response = _response(
        status,
        intent=intent,
        target=target,
        description=description,
        exit_code=result.returncode,
        stdout=_bounded_output(result.stdout, MAX_STDOUT_BYTES),
        stderr=_bounded_output(result.stderr, MAX_STDERR_BYTES),
        elapsed_secs=round(time.monotonic() - started, 3),
    )
    audit_log.log_action(
        phase="EXECUTED" if result.returncode == 0 else "FAILED",
        action={"action": intent, "target": target},
        result=response.get("description") if result.returncode == 0 else None,
        error=response.get("stderr") if result.returncode != 0 else None,
    )
    return response


def _process_intent(payload: Any) -> dict[str, Any]:
    started = time.monotonic()
    if not isinstance(payload, dict):
        return _response("REJECTED", error="Payload must be a JSON object.")

    intent = payload.get("intent")
    if not isinstance(intent, str) or not intent:
        return _response("REJECTED", error="Intent must be a non-empty string.")
    if any(character in intent for character in "&|;$`>< "):
        return _response(
            "REJECTED",
            error="SECURITY: Raw shell strings are prohibited in the intent field.",
        )

    if intent == "EXTERNAL_ACTION":
        return _response(
            "REJECTED",
            intent=intent,
            error=(
                "EXTERNAL_ACTION is not a privileged host intent. The root Host "
                "Executor never launches browser, computer-use, or user-file bridges."
            ),
        )

    if intent not in _VALID_INTENTS:
        return _response(
            "REJECTED",
            error=f"Unknown intent '{intent}'. Valid intents: {sorted(_VALID_INTENTS)}",
        )
    extra_fields = set(payload) - {"intent", "target"}
    if extra_fields:
        return _response(
            "REJECTED", error=f"Unexpected payload fields: {sorted(extra_fields)}"
        )

    try:
        target = _validate_intent_target(intent, payload.get("target", ""))
    except ValueError as exc:
        return _response("REJECTED", intent=intent, error=str(exc))

    with _operation_lock:
        return _execute_locked_intent(intent, target, started)


async def _write_response(
    writer: asyncio.StreamWriter, response: dict[str, Any]
) -> None:
    encoded = json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(encoded) > MAX_RESPONSE_BYTES:
        encoded = json.dumps(
            _response("ERROR", error="Executor response exceeded its size limit."),
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    writer.write(encoded)
    await writer.drain()


async def _handle_client(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        try:
            pid, peer_uid, _peer_gid = _peer_credentials(writer)
            authorized_uid = _resolve_authorized_uid()
        except (PermissionError, RuntimeError) as exc:
            log.warning("Rejecting unverifiable executor peer: %s", exc)
            await _write_response(
                writer, _response("REJECTED", error="Unauthorized executor peer.")
            )
            return

        if peer_uid != authorized_uid:
            log.warning(
                "Rejecting executor peer pid=%d uid=%d; required uid=%d",
                pid,
                peer_uid,
                authorized_uid,
            )
            await _write_response(
                writer, _response("REJECTED", error="Unauthorized executor peer UID.")
            )
            return

        raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
        if not raw:
            await _write_response(writer, _response("REJECTED", error="Empty payload."))
            return
        if len(raw) > MAX_PAYLOAD_BYTES:
            await _write_response(
                writer,
                _response(
                    "REJECTED", error=f"Payload exceeds {MAX_PAYLOAD_BYTES} bytes."
                ),
            )
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            await _write_response(writer, _response("REJECTED", error="Invalid JSON payload."))
            return

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _process_intent, payload)
        await _write_response(writer, response)
    except (asyncio.TimeoutError, ConnectionResetError):
        log.warning("Executor client disconnected or timed out.")
    except Exception:
        log.exception("Unexpected executor client error.")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _run_server() -> None:
    authorized_uid = _resolve_authorized_uid()
    socket_gid = _resolve_socket_group()
    listener = _create_listening_socket()
    try:
        server = await asyncio.start_unix_server(
            _handle_client,
            sock=listener,
            start_serving=False,
            limit=MAX_PAYLOAD_BYTES + 1,
        )
    except Exception:
        listener.close()
        _unlink_socket()
        raise

    _configure_socket_permissions(SOCKET_PATH, socket_gid)
    await server.start_serving()
    log.info(
        "Listening on %s as root:%s; only %s (uid=%d) is authorized",
        SOCKET_PATH,
        SOCKET_GROUP,
        AUTHORIZED_USER,
        authorized_uid,
    )

    stop_event = asyncio.Event()

    def stop(signum: int, _frame: Any) -> None:
        log.info("Received %s; stopping", signal.Signals(signum).name)
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        async with server:
            await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        server.close()
        await server.wait_closed()
        _unlink_socket()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )
    if os.getuid() != 0:
        log.critical("Host Executor must run as root.")
        raise SystemExit(1)
    try:
        asyncio.run(_run_server())
    except KeyboardInterrupt:
        raise SystemExit(0) from None
    except Exception:
        log.exception("Host Executor failed.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
