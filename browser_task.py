# Copyright (c) 2026 Euryale Ferox Private Limited
# SPDX-License-Identifier: MIT

"""Validation contract for future user-approved browser tasks."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_APPROVAL_ID = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_SCHEMA = {
    "action",
    "instruction",
    "allowed_origins",
    "verification",
    "expected",
    "approval_id",
    "task_id",
}


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{field} is invalid.")
    if any(not character.isprintable() and not character.isspace() for character in value):
        raise ValueError(f"{field} contains control characters.")
    return value.strip()


def _origin(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("allowed_origins must contain strings.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("allowed_origins contains an invalid origin.") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("allowed_origins must contain HTTPS origins only.")
    return f"https://{parsed.hostname}" + (f":{port}" if port else "")


def validate_browser_task(task: Any, *, user_originated: bool) -> dict[str, Any]:
    """Validate one browser task before it can reach a model or worker."""
    if not user_originated:
        raise PermissionError("Browser tasks must be user-originated.")
    if not isinstance(task, dict) or set(task) != _SCHEMA or task.get("action") != "browser_task":
        raise ValueError("browser_task fields do not match the required schema.")
    task_id = task.get("task_id")
    approval_id = task.get("approval_id")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise ValueError("task_id is invalid.")
    if not isinstance(approval_id, str) or not _APPROVAL_ID.fullmatch(approval_id):
        raise ValueError("approval_id is invalid.")
    origins = task.get("allowed_origins")
    if not isinstance(origins, list) or not 1 <= len(origins) <= 8:
        raise ValueError("allowed_origins must contain from one to eight origins.")
    normalized_origins = [_origin(origin) for origin in origins]
    if len(set(normalized_origins)) != len(normalized_origins):
        raise ValueError("allowed_origins cannot contain duplicates.")
    if task.get("verification") != "visible_text":
        raise ValueError("verification must be visible_text.")
    return {
        "action": "browser_task",
        "task_id": task_id,
        "instruction": _text(task.get("instruction"), "instruction", 2000),
        "allowed_origins": normalized_origins,
        "verification": "visible_text",
        "expected": _text(task.get("expected"), "expected", 512),
        "approval_id": approval_id,
    }
