"""Fail-closed human confirmation and audit support for external actions."""

from __future__ import annotations

import json
import logging
import os
import secrets
import stat
import sys
from typing import Any

try:
    from . import audit_log
except ImportError:
    import audit_log

log = logging.getLogger("yantra.confirmation")

_DEFAULT_COUNTER_PATH = os.path.join(
    os.path.expanduser("~"), ".local", "state", "yantra", "confirmation_counter.json"
)
_DEFAULT_COUNTER_PATH = os.environ.get(
    "YANTRA_CONFIRMATION_COUNTER_PATH", _DEFAULT_COUNTER_PATH
)
COUNTER_PATH = _DEFAULT_COUNTER_PATH
_MAX_COUNTER_BYTES = 4096


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _open_counter_directory(path: str) -> tuple[int, str]:
    directory = os.path.dirname(path)
    name = os.path.basename(path)
    if not directory or not name or name in {".", ".."}:
        raise ValueError("Confirmation counter path is invalid.")

    os.makedirs(directory, mode=0o700, exist_ok=True)
    directory_fd = os.open(directory, _directory_flags())
    metadata = os.fstat(directory_fd)
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        os.close(directory_fd)
        raise PermissionError("Confirmation counter directory has unsafe ownership.")
    os.fchmod(directory_fd, 0o700)
    if stat.S_IMODE(os.fstat(directory_fd).st_mode) != 0o700:
        os.close(directory_fd)
        raise PermissionError("Confirmation counter directory could not be secured.")
    return directory_fd, name


def _resolve_counter_path() -> str:
    """Validate the configured path without silently changing trust domains."""
    directory_fd, _ = _open_counter_directory(COUNTER_PATH)
    os.close(directory_fd)
    return COUNTER_PATH


def _safe_existing_counter(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise PermissionError("Confirmation counter must be an owned regular file.")
    return metadata


def _read_counter() -> int:
    """Read a small, owned, non-symlink counter; invalid state fails to zero."""
    try:
        path = _resolve_counter_path()
        directory_fd, name = _open_counter_directory(path)
        try:
            metadata = _safe_existing_counter(directory_fd, name)
            if metadata is None:
                return 0
            if stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_size > _MAX_COUNTER_BYTES:
                return 0
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(name, flags, dir_fd=directory_fd)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_uid != os.geteuid()
                    or stat.S_IMODE(opened.st_mode) != 0o600
                    or opened.st_size > _MAX_COUNTER_BYTES
                ):
                    return 0
                raw = os.read(descriptor, _MAX_COUNTER_BYTES + 1)
            finally:
                os.close(descriptor)
        finally:
            os.close(directory_fd)

        data = json.loads(raw.decode("utf-8"))
        count = data.get("confirmed_runs", 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return 0
        return count
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return 0


def _write_counter(count: int) -> bool:
    """Atomically replace the counter with a 0600 non-symlink regular file."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("Confirmation counter must be a non-negative integer.")

    directory_fd = -1
    temporary_name = ""
    try:
        path = _resolve_counter_path()
        directory_fd, name = _open_counter_directory(path)
        _safe_existing_counter(directory_fd, name)

        temporary_name = f".{name}.{secrets.token_hex(8)}.tmp"
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
        try:
            os.fchmod(descriptor, 0o600)
            payload = json.dumps(
                {"confirmed_runs": count}, separators=(",", ":")
            ).encode("utf-8")
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

        os.replace(
            temporary_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = ""
        os.fsync(directory_fd)
        return True
    except (OSError, ValueError) as exc:
        log.error("Failed to persist confirmation counter: %s", exc)
        return False
    finally:
        if directory_fd >= 0:
            if temporary_name:
                try:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
            os.close(directory_fd)


def get_run_number() -> int:
    return _read_counter() + 1


def needs_confirmation() -> bool:
    """External actions always need confirmation; counters are audit-only."""
    return True


def requires_confirmation(_action: dict[str, Any]) -> bool:
    """Fail closed for network, computer-use, file, and unknown external actions."""
    return True


def _format_action_summary(action: dict[str, Any]) -> str:
    parts = [f"  Action: {action.get('action', 'unknown')}"]
    for key in (
        "operation",
        "url",
        "path",
        "destination",
        "target",
        "task",
        "instruction",
        "proposed_action",
    ):
        if key in action:
            value = action[key]
            if key == "proposed_action":
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            clean = "".join(
                character
                for character in str(value)
                if character in "\n\t" or ord(character) >= 32
            )
            parts.append(f"  {key}: {clean[:2000]}")
    return "\n".join(parts)


def confirm_action(action: dict[str, Any]) -> bool:
    """Require an interactive human decision for every external action."""
    run_number = get_run_number()
    if not audit_log.log_action(
        phase="PROPOSED", action=action, run_number=run_number
    ):
        log.error("Refusing action because its proposal audit could not be persisted.")
        return False

    if not sys.stdin.isatty():
        log.warning("No TTY is available; rejecting external action.")
        audit_log.log_action(
            phase="REJECTED",
            action=action,
            run_number=run_number,
            confirmation="no_tty",
            error="No interactive confirmation channel is available.",
        )
        return False

    print("\n" + "=" * 60)
    print(f"  ACTION CONFIRMATION REQUIRED (run {run_number})")
    print("=" * 60)
    print(_format_action_summary(action))
    print("-" * 60)
    try:
        response = input("  Execute this action? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        response = ""

    approved = response in {"y", "yes"}
    if approved:
        if not _write_counter(_read_counter() + 1):
            log.error("Refusing action because confirmation state was not persisted.")
            return False
        if not audit_log.log_action(
            phase="CONFIRMED",
            action=action,
            run_number=run_number,
            confirmation="user_confirmed",
        ):
            log.error("Refusing action because confirmation audit was not persisted.")
            return False
        return True

    audit_log.log_action(
        phase="REJECTED",
        action=action,
        run_number=run_number,
        confirmation="user_rejected",
    )
    return False


def log_execution_outcome(
    action: dict[str, Any],
    *,
    success: bool,
    result_msg: str = "",
    error_msg: str = "",
) -> None:
    run_number = max(1, get_run_number() - 1)
    if success:
        audit_log.log_action(
            phase="EXECUTED",
            action=action,
            run_number=run_number,
            result=result_msg or "Action completed successfully.",
        )
    else:
        audit_log.log_action(
            phase="FAILED",
            action=action,
            run_number=run_number,
            error=error_msg or "Action execution failed.",
        )
