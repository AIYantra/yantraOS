"""
YantraOS - Immutable Audit Log
Target: /opt/yantra/core/audit_log.py

Synchronous, append-only logger for sandbox execution outcomes.
Provides a verifiable trust artifact of all actions taken by the Kriya Loop.
"""

from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import logging
import os
import re
import stat
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sandbox import SandboxResult

log = logging.getLogger("yantra.audit_log")

DEFAULT_AUDIT_LOG_PATH = "/var/log/yantra/audit.jsonl"
AUDIT_LOG_PATH = os.environ.get("YANTRA_AUDIT_LOG_PATH", DEFAULT_AUDIT_LOG_PATH)

MAX_AUDIT_STRING_BYTES = 2048
MAX_AUDIT_ENTRY_BYTES = 16384
_MAX_AUDIT_DEPTH = 8
_MAX_AUDIT_ITEMS = 100
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_AUDIT_FLAGS = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _split_state_path(path: str | os.PathLike[str]) -> tuple[str, str]:
    path = os.fspath(path)
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise ValueError(f"Audit path must be absolute and normalized: {path!r}")
    directory, filename = os.path.split(path)
    if not filename:
        raise ValueError("Audit path must name a file")
    return directory, filename


def _validate_directory(info: os.stat_result, *, created: bool) -> None:
    mode = stat.S_IMODE(info.st_mode)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Audit parent is not a directory")
    if created:
        if info.st_uid != os.geteuid() or mode != 0o700:
            raise PermissionError("New audit directories must be owned by the service with mode 0700")
        return
    if os.geteuid() != 0 and info.st_uid not in (os.geteuid(), 0):
        raise PermissionError("Audit parent has an untrusted owner")
    if mode not in (0o700, 0o750):
        raise PermissionError("Existing audit parent must have mode 0700 or 0750")


def _open_secure_parent(path: str | os.PathLike[str]) -> tuple[int, str]:
    directory, filename = _split_state_path(path)
    current_fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        parts = [part for part in directory.split(os.sep) if part]
        for index, part in enumerate(parts):
            created = False
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=current_fd)
                    os.fsync(current_fd)
                    created = True
                except FileExistsError:
                    pass
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)

            os.close(current_fd)
            current_fd = next_fd
            if created:
                os.fchmod(current_fd, 0o700)
                os.fsync(current_fd)
            if index == len(parts) - 1:
                _validate_directory(os.fstat(current_fd), created=created)

        if not parts:
            _validate_directory(os.fstat(current_fd), created=False)
        return current_fd, filename
    except Exception:
        os.close(current_fd)
        raise


def _validate_audit_file(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Audit path is not a regular file")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise PermissionError("Audit file must have mode 0600")
    if os.geteuid() != 0 and info.st_uid != os.geteuid():
        raise PermissionError("Audit file is not owned by the service")


def _open_audit_file() -> int:
    parent_fd, filename = _open_secure_parent(AUDIT_LOG_PATH)
    created = False
    try:
        try:
            fd = os.open(
                filename,
                _AUDIT_FLAGS | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
            created = True
            before = None
        except FileExistsError:
            before = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
            _validate_audit_file(before)
            fd = os.open(filename, _AUDIT_FLAGS, dir_fd=parent_fd)

        try:
            if created:
                os.fchmod(fd, 0o600)
            after = os.fstat(fd)
            _validate_audit_file(after)
            if before is not None and (before.st_dev, before.st_ino) != (
                after.st_dev,
                after.st_ino,
            ):
                raise RuntimeError("Audit file changed while being opened")
            if created:
                os.fsync(fd)
                os.fsync(parent_fd)
            return fd
        except Exception:
            os.close(fd)
            raise
    finally:
        os.close(parent_fd)


def _resolve_log_path() -> str:
    """Validate or securely create the configured audit file."""
    fd = _open_audit_file()
    os.close(fd)
    return os.fspath(AUDIT_LOG_PATH)


def _value_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return repr(value).encode("utf-8", errors="replace")


def _metadata(value: Any, marker: str) -> dict[str, Any]:
    raw = _value_bytes(value)
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        marker: True,
    }


def _bounded_text(value: Any, limit: int = MAX_AUDIT_STRING_BYTES) -> str:
    text = value if isinstance(value, str) else str(value)
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    digest = hashlib.sha256(raw).hexdigest()
    suffix = f"... [truncated bytes={len(raw)} sha256={digest}]"
    prefix = raw[: max(0, limit - len(suffix.encode("ascii")))].decode(
        "utf-8", errors="ignore"
    )
    return prefix + suffix


def _is_secret_field(name: Any) -> bool:
    if not isinstance(name, str):
        return False
    words = re.findall(
        r"[a-z0-9]+",
        re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower(),
    )
    return bool(
        {"key", "token", "password", "passwd", "authorization", "secret", "credential"}
        & set(words)
        or "apikey" in words
    )


def _sanitize_action(
    value: Any,
    *,
    redact_content: bool = False,
    depth: int = 0,
    seen: set[int] | None = None,
) -> Any:
    if depth >= _MAX_AUDIT_DEPTH:
        return _metadata(value, "truncated")
    if isinstance(value, str):
        return _bounded_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        return _metadata(value, "redacted")

    seen = seen if seen is not None else set()
    if isinstance(value, dict):
        if id(value) in seen:
            return {"truncated": True, "reason": "recursive value"}
        seen.add(id(value))
        sanitized: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:_MAX_AUDIT_ITEMS]:
            output_key = _bounded_text(key, 256)
            if _is_secret_field(key) or (
                redact_content and isinstance(key, str) and key.lower() == "content"
            ):
                sanitized[output_key] = _metadata(item, "redacted")
            else:
                sanitized[output_key] = _sanitize_action(
                    item,
                    redact_content=redact_content,
                    depth=depth + 1,
                    seen=seen,
                )
        if len(items) > _MAX_AUDIT_ITEMS:
            sanitized["_truncated_items"] = len(items) - _MAX_AUDIT_ITEMS
        seen.remove(id(value))
        return sanitized

    if isinstance(value, (list, tuple)):
        if id(value) in seen:
            return [{"truncated": True, "reason": "recursive value"}]
        seen.add(id(value))
        sanitized_list = [
            _sanitize_action(
                item,
                redact_content=redact_content,
                depth=depth + 1,
                seen=seen,
            )
            for item in value[:_MAX_AUDIT_ITEMS]
        ]
        if len(value) > _MAX_AUDIT_ITEMS:
            sanitized_list.append({"truncated_items": len(value) - _MAX_AUDIT_ITEMS})
        seen.remove(id(value))
        return sanitized_list

    return _bounded_text(value)


def _encode_payload(payload: dict[str, Any]) -> bytes:
    def encode() -> bytes:
        return (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
            + "\n"
        ).encode("utf-8")

    encoded = encode()
    if len(encoded) <= MAX_AUDIT_ENTRY_BYTES:
        return encoded

    for field in ("action_detail", "result", "error"):
        if field in payload:
            payload[field] = _metadata(payload[field], "truncated")
            encoded = encode()
            if len(encoded) <= MAX_AUDIT_ENTRY_BYTES:
                return encoded
    raise ValueError("Audit entry exceeds the configured size limit")


def _append_payload(payload: dict[str, Any]) -> None:
    fd = _open_audit_file()
    locked = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        locked = True
        size = os.fstat(fd).st_size
        previous_hash = "0" * 64
        if size:
            start = max(0, size - 65_536)
            os.lseek(fd, start, os.SEEK_SET)
            tail = os.read(fd, size - start)
            lines = [line for line in tail.splitlines() if line]
            if lines:
                try:
                    previous = json.loads(lines[-1])
                    candidate = previous.get("entry_hash")
                    if isinstance(candidate, str) and re.fullmatch(r"[0-9a-f]{64}", candidate):
                        previous_hash = candidate
                    else:
                        previous_hash = hashlib.sha256(lines[-1]).hexdigest()
                except (json.JSONDecodeError, AttributeError):
                    raise ValueError("Existing audit tail is malformed")
        chained = dict(payload)
        chained["previous_hash"] = previous_hash
        canonical = json.dumps(
            chained,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        chained["entry_hash"] = hashlib.sha256(
            previous_hash.encode("ascii") + canonical
        ).hexdigest()
        encoded = _encode_payload(chained)
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("Short audit write")
            view = view[written:]
        os.fsync(fd)
    finally:
        try:
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def log_execution(script: str, result: "SandboxResult") -> bool:
    """Append one sandbox execution record without exposing the script."""
    try:
        payload = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
            "image_used": _bounded_text(getattr(result, "image", "unknown")),
            "container_id": _bounded_text(getattr(result, "container_id", "unknown")),
            "exit_code": getattr(result, "exit_code", 0),
            "duration_ms": int(getattr(result, "duration_secs", 0) * 1000),
        }
        _append_payload(payload)
        return True
    except Exception as exc:
        log.error("> AUDIT: Failed to append to audit log: %s", exc)
        return False


def log_action(
    *,
    phase: str,
    action: dict,
    run_number: int | None = None,
    confirmation: str | None = None,
    result: str | None = None,
    error: str | None = None,
) -> bool:
    """
    Append a redacted external-action audit entry.

    ``phase`` identifies proposal, confirmation, execution, or failure;
    ``run_number`` and ``confirmation`` preserve the confirmation trail.
    ``result`` and ``error`` carry bounded outcome summaries.
    """
    try:
        action_type = action.get("action", "unknown")
        payload: dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "log_type": "external_action",
            "phase": _bounded_text(phase, 128),
            "action_type": _bounded_text(action_type, 128),
            "action_detail": _sanitize_action(
                action,
                redact_content=action_type == "file_management",
            ),
        }

        if run_number is not None:
            payload["run_number"] = run_number
        if confirmation is not None:
            payload["confirmation"] = _bounded_text(confirmation, 128)
        if result is not None:
            payload["result"] = _bounded_text(result)
        if error is not None:
            payload["error"] = _bounded_text(error)

        _append_payload(payload)
        return True
    except Exception as exc:
        log.error("> AUDIT: Failed to append action log: %s", exc)
        return False
