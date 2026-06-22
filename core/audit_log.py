"""
YantraOS — Immutable Audit Log
Target: /opt/yantra/core/audit_log.py

Synchronous, append-only logger for sandbox execution outcomes.
Provides a verifiable trust artifact of all actions taken by the Kriya Loop.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sandbox import SandboxResult

log = logging.getLogger("yantra.audit_log")

AUDIT_LOG_PATH = "/var/log/yantra/audit.jsonl"


def log_execution(script: str, result: "SandboxResult") -> None:
    """
    Append a single, flat JSON line to the audit log.
    Ensures directory exists with safe permissions before writing.
    """
    try:
        log_dir = os.path.dirname(AUDIT_LOG_PATH)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            # Ensure safe permissions for the log directory
            os.chmod(log_dir, 0o755)

        script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()
        
        # duration is often provided in seconds in SandboxResult, convert to ms
        duration_ms = int(result.duration_secs * 1000) if hasattr(result, "duration_secs") else 0

        # container_id might be provided or None, handle gracefully
        container_id = getattr(result, "container_id", "unknown")
        # image_used might not be directly in SandboxResult, fallback to "alpine:latest" as a common default if missing
        # We can extract it if needed or assume the sandbox used a default image.
        image_used = getattr(result, "image", "alpine:latest")

        payload = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "script_sha256": script_hash,
            "image_used": image_used,
            "container_id": container_id,
            "exit_code": result.exit_code,
            "duration_ms": duration_ms,
        }

        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    except Exception as exc:
        # Fallback to standard logging if the audit log is unwritable,
        # but do not crash the engine.
        log.error(f"> AUDIT: Failed to append to audit log: {exc}")
