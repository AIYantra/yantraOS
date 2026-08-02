# Copyright (c) 2026 Euryale Ferox Private Limited
# SPDX-License-Identifier: MIT

"""Small client for the private Yantra browser-worker Unix socket."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any


class BrowserWorkerClient:
    def __init__(self, socket_path: str = "/run/yantra-browser/worker.sock") -> None:
        self.socket_path = Path(socket_path)

    def _request(self, operation: str, **payload: Any) -> dict[str, Any]:
        request = json.dumps({"operation": operation, **payload}, separators=(",", ":")).encode("utf-8") + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(30)
            connection.connect(str(self.socket_path))
            connection.sendall(request)
            response = bytearray()
            while b"\n" not in response and len(response) <= 8 * 1024 * 1024:
                block = connection.recv(65536)
                if not block:
                    break
                response.extend(block)
        if b"\n" not in response or len(response) > 8 * 1024 * 1024:
            raise RuntimeError("Browser worker returned an invalid response.")
        parsed = json.loads(bytes(response).split(b"\n", 1)[0])
        if not isinstance(parsed, dict) or not isinstance(parsed.get("ok"), bool):
            raise RuntimeError("Browser worker response is malformed.")
        if not parsed["ok"]:
            raise RuntimeError(str(parsed.get("error", "Browser worker failed.")))
        result = parsed.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Browser worker result is malformed.")
        return result

    def start_task(self, task_id: str, html: str) -> dict[str, Any]:
        return self._request("start_task", task_id=task_id, html=html)

    def screenshot(self) -> dict[str, Any]:
        return self._request("screenshot")

    def act(self, action: dict[str, Any]) -> dict[str, Any]:
        return self._request("act", action=action)

    def verify(self, expected: str) -> bool:
        return bool(self._request("verify", expected=expected).get("passed"))

    def close_task(self) -> None:
        self._request("close_task")
