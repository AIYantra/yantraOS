# Copyright (c) 2026 Euryale Ferox Private Limited
# SPDX-License-Identifier: MIT

"""Unprivileged Playwright and managed-output bridge for confirmed actions."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("yantra.local_bridge")

_VISIBLE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.()-]*$")
_MAX_URL_CHARS = 4096
_MAX_PATH_CHARS = 512
_MAX_INSTRUCTION_CHARS = 2000
_MAX_CONTENT_BYTES = 1_048_576
_OUTPUT_ROOT_ENV = "YANTRA_ACTION_ROOT"
_MAX_INTENT_BYTES = 2 * 1_048_576
_ACTION_SCHEMAS = {
    "open_url": ({"action", "url"}, set()),
    "create_dummy_file": ({"action", "path"}, {"content"}),
    "navigate_and_extract": (
        {"action", "url", "instruction", "output_path"},
        set(),
    ),
}


def _require_unprivileged_user() -> None:
    if os.geteuid() == 0:
        raise PermissionError("The Foundry action bridge refuses to run as UID 0.")


def _require_browser_enabled() -> None:
    raise PermissionError(
        "Browser actions are disabled until traffic is confined to an isolated "
        "egress proxy that pins validated IPs."
    )


def _validate_url(url: Any) -> str:
    """Allow only credential-free public HTTP(S) destinations."""
    if not isinstance(url, str) or not url or len(url) > _MAX_URL_CHARS:
        raise ValueError("URL is missing or exceeds its size limit.")
    if any(character.isspace() or ord(character) < 32 for character in url) or "\\" in url:
        raise ValueError("SECURITY: URL contains whitespace or control characters.")

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("SECURITY: URL authority or port is invalid.") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("SECURITY: Only http and https URLs are permitted.")
    if not parsed.hostname:
        raise ValueError("SECURITY: URL must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("SECURITY: URL credentials are prohibited.")
    if parsed.fragment:
        raise ValueError("SECURITY: URL fragments are prohibited.")

    return url


def _validate_path(path: Any) -> tuple[str, ...]:
    """Return visible relative components for one managed output root."""
    if not isinstance(path, str) or not path or len(path) > _MAX_PATH_CHARS:
        raise ValueError("Managed output path is missing or exceeds its size limit.")
    if path != path.strip() or path.startswith(("/", "~")) or "\\" in path:
        raise ValueError("SECURITY: Output path must be a relative managed path.")
    parts = tuple(path.split("/"))
    if any(
        not part
        or part in {".", ".."}
        or part.startswith(".")
        or not _VISIBLE_PATH_COMPONENT.fullmatch(part)
        for part in parts
    ):
        raise ValueError("SECURITY: Output paths must contain only visible components.")
    return parts


def _validate_content(content: Any) -> str:
    if not isinstance(content, str):
        raise ValueError("SECURITY: File content must be a string.")
    if len(content.encode("utf-8")) > _MAX_CONTENT_BYTES:
        raise ValueError(f"SECURITY: File content exceeds {_MAX_CONTENT_BYTES} bytes.")
    if "\x00" in content:
        raise ValueError("SECURITY: File content contains a NUL byte.")
    return content


def _validate_instruction(instruction: Any) -> str:
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Extraction instruction must be a non-empty string.")
    instruction = instruction.strip()
    if len(instruction) > _MAX_INSTRUCTION_CHARS or "\x00" in instruction:
        raise ValueError("Extraction instruction exceeds its safety limits.")
    return instruction


def validate_intent(intent: Any) -> None:
    """Validate a typed built-in browser or managed-output action."""
    _validate_intent(intent)


def _validate_intent(intent: Any) -> None:
    if not isinstance(intent, dict):
        raise ValueError("Intent must be a JSON object.")
    action = intent.get("action")
    if action not in _ACTION_SCHEMAS:
        raise ValueError(f"Unknown built-in action: {action!r}.")
    required, optional = _ACTION_SCHEMAS[action]
    if not required <= set(intent) or set(intent) - required - optional:
        raise ValueError(f"Intent fields do not match the '{action}' schema.")
    if action in {"open_url", "navigate_and_extract"}:
        _validate_url(intent["url"])
    if action == "create_dummy_file":
        _validate_path(intent["path"])
        _validate_content(intent.get("content", ""))
    if action == "navigate_and_extract":
        _validate_instruction(intent["instruction"])
        _validate_path(intent["output_path"])


def _execute_intent(intent: dict[str, Any]) -> None:
    action = intent["action"]
    if action == "create_dummy_file":
        create_dummy_file(intent["path"], intent.get("content", ""))
    elif action == "open_url":
        open_url(intent["url"])
    else:
        navigate_and_extract(intent["url"], intent["instruction"], intent["output_path"])


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _open_managed_root() -> tuple[Path, int]:
    home = Path.home().resolve()
    configured = os.getenv(_OUTPUT_ROOT_ENV)
    root = (
        Path(configured).expanduser()
        if configured
        else home / "Documents" / "YantraOS" / "Foundry"
    )
    if not root.is_absolute():
        raise ValueError("SECURITY: Managed output root must be absolute.")
    if root.is_symlink():
        raise ValueError("SECURITY: Managed output root must not be a symlink.")
    resolved_parent = root.parent.resolve(strict=False)
    if resolved_parent != home and home not in resolved_parent.parents:
        raise ValueError("SECURITY: Managed output root must remain inside HOME.")

    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor = os.open(root, _directory_flags())
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        os.close(descriptor)
        raise PermissionError("SECURITY: Managed output root has unsafe ownership.")
    os.fchmod(descriptor, 0o700)
    return root.resolve(), descriptor


def _open_managed_parent(root_fd: int, parts: tuple[str, ...]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            try:
                os.mkdir(component, 0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(component, _directory_flags(), dir_fd=current_fd)
            metadata = os.fstat(next_fd)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
                os.close(next_fd)
                raise PermissionError("SECURITY: Managed output directory is unsafe.")
            os.fchmod(next_fd, 0o700)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _ensure_output_available(path: str) -> None:
    parts = _validate_path(path)
    _root, root_fd = _open_managed_root()
    try:
        parent_fd = _open_managed_parent(root_fd, parts)
        try:
            try:
                os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise FileExistsError("SECURITY: Refusing to overwrite an existing output.")
        finally:
            os.close(parent_fd)
    finally:
        os.close(root_fd)


def _exclusive_write(path: str, data: bytes) -> Path:
    parts = _validate_path(path)
    root, root_fd = _open_managed_root()
    parent_fd = -1
    descriptor = -1
    created = False
    try:
        parent_fd = _open_managed_parent(root_fd, parts)
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(parts[-1], flags, 0o600, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise FileExistsError(
                "SECURITY: Refusing to overwrite an existing or symlink output."
            ) from exc
        created = True
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            descriptor = -1
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(parent_fd)
        return root.joinpath(*parts)
    except Exception:
        if created and parent_fd >= 0:
            try:
                os.unlink(parts[-1], dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)
        os.close(root_fd)


def _safe_log_intent(intent: dict[str, Any]) -> str:
    safe: dict[str, Any] = {}
    for key, value in intent.items():
        if key == "content":
            safe[key] = f"<{len(str(value))} chars, redacted>"
        elif isinstance(value, str):
            safe[key] = value[:120]
        else:
            safe[key] = value
    return json.dumps(safe)


def create_dummy_file(path: str, content: str) -> None:
    _require_unprivileged_user()
    content = _validate_content(content)
    output = _exclusive_write(path, content.encode("utf-8"))
    log.info("Created managed output %s", output)


def open_url(url: str) -> None:
    _require_unprivileged_user()
    _require_browser_enabled()


def navigate_and_extract(url: str, instruction: str, output_path: str) -> None:
    _require_unprivileged_user()
    _require_browser_enabled()


def _report_error(error_type: str, message: str, exit_code: int = 1) -> None:
    sys.stderr.write(json.dumps({"error_type": error_type, "message": message}) + "\n")
    raise SystemExit(exit_code)


def main() -> None:
    try:
        _require_unprivileged_user()
    except PermissionError as exc:
        _report_error("PERMISSION_ERROR", str(exc))

    encoded_intent = sys.stdin.buffer.read(_MAX_INTENT_BYTES + 1)
    if not encoded_intent or len(encoded_intent) > _MAX_INTENT_BYTES:
        _report_error("INPUT_ERROR", "Intent stdin is empty or too large.")
    try:
        intent = json.loads(encoded_intent.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _report_error("JSON_PARSE_ERROR", f"Invalid JSON: {exc}")

    try:
        _validate_intent(intent)
    except ValueError as exc:
        _report_error("VALIDATION_ERROR", str(exc))
    log.info("Received intent: %s", _safe_log_intent(intent))

    try:
        from .action_confirmation import confirm_action
    except ImportError:
        from action_confirmation import confirm_action
    if "--approved" not in sys.argv and not confirm_action(intent):
        _report_error("CONFIRMATION_REJECTED", "Action was not approved.", 3)

    try:
        _execute_intent(intent)
    except PermissionError as exc:
        _report_error("PERMISSION_ERROR", str(exc))
    except TimeoutError as exc:
        _report_error("TIMEOUT_ERROR", str(exc))
    except Exception as exc:
        _report_error("EXECUTION_ERROR", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
