"""Focused tests for the GUI's disabled privileged external-action path."""

from __future__ import annotations

import json
import os
import socket
import stat
import struct
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

import core.host_executor as host_executor
from ui.gui_shell import (
    ExternalActionSocketClient,
    ExternalActionWorker,
    YantraMainWindow,
    safe_display_text,
)


class _SocketContext:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent = b""
        self.connected_path = ""
        self.timeout = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def connect(self, path: str) -> None:
        self.connected_path = path

    def sendall(self, payload: bytes) -> None:
        self.sent = payload

    def recv(self, _size: int) -> bytes:
        response, self.response = self.response, b""
        return response

    def getsockopt(self, _level: int, _option: int, _size: int) -> bytes:
        return struct.pack("3i", 123, 0, 456)


class ExternalActionSocketClientTests(unittest.TestCase):
    def test_builds_external_request_only_for_policy_rejection(self) -> None:
        payload = ExternalActionSocketClient.build_payload("  Open Telegram  ")
        self.assertEqual(payload, {
            "intent": "EXTERNAL_ACTION",
            "target": "",
            "action_payload": {
                "action": "computer_use_task",
                "instruction": "Open Telegram",
            },
        })
        result = host_executor._process_intent(payload)
        self.assertEqual(result["status"], "REJECTED")

    def test_rejects_empty_oversized_prohibited_and_hidden_input(self) -> None:
        for instruction in (
            "",
            " " * 5,
            "x" * 2001,
            "open; shutdown",
            "open\x00app",
            "open\u200bapp",
            "open\u202eapp",
            "open\ud800app",
        ):
            with self.subTest(instruction=repr(instruction[:20])):
                with self.assertRaises(ValueError):
                    ExternalActionSocketClient.build_payload(instruction)

    def test_sends_request_and_accepts_only_clear_root_rejection(self) -> None:
        fake_socket = _SocketContext(
            b'{"status":"REJECTED","intent":"EXTERNAL_ACTION",'
            b'"error":"root external actions are disabled"}\n'
        )
        socket_factory = MagicMock(return_value=fake_socket)
        client = ExternalActionSocketClient(
            "/tmp/executor.sock", timeout=7.0, verify_socket=False
        )

        with patch("ui.gui_shell.socket.socket", socket_factory):
            response = client.execute("Open Telegram")

        self.assertEqual(fake_socket.connected_path, "/tmp/executor.sock")
        self.assertEqual(fake_socket.timeout, 7.0)
        self.assertTrue(fake_socket.sent.endswith(b"\n"))
        self.assertNotIn("confirmation", json.loads(fake_socket.sent))
        self.assertEqual(response["status"], "REJECTED")

    def test_success_confirmation_and_malformed_responses_are_rejected(self) -> None:
        responses = (
            b"",
            b"not-json\n",
            b"[]\n",
            b'{"status":"REJECTED"}',
            b'{"status":"SUCCESS","intent":"EXTERNAL_ACTION"}\n',
            b'{"status":"CONFIRMATION_REQUIRED","intent":"EXTERNAL_ACTION"}\n',
            b'{"status":"REJECTED","intent":"SYSTEM_UPDATE","error":"no"}\n',
            b'{"status":"REJECTED","intent":"EXTERNAL_ACTION"}\n',
        )
        for response in responses:
            with self.subTest(response=response), patch(
                "ui.gui_shell.socket.socket", return_value=_SocketContext(response)
            ):
                with self.assertRaises(RuntimeError):
                    ExternalActionSocketClient(
                        "/tmp/test.sock", verify_socket=False
                    ).execute("Wait")

    def test_requires_root_owned_private_unix_socket(self) -> None:
        client = ExternalActionSocketClient("/run/yantra/executor.sock")
        secure_mode = stat.S_IFSOCK | 0o660
        with patch("ui.gui_shell.os.lstat") as lstat:
            lstat.return_value = os.stat_result((secure_mode, 0, 0, 1, 0, 0, 0, 0, 0, 0))
            client._verify_socket_path()

            lstat.return_value = os.stat_result((secure_mode, 0, 0, 1, 1000, 0, 0, 0, 0, 0))
            with self.assertRaises(ConnectionError):
                client._verify_socket_path()

            lstat.return_value = os.stat_result((secure_mode | stat.S_IWOTH, 0, 0, 1, 0, 0, 0, 0, 0, 0))
            with self.assertRaises(ConnectionError):
                client._verify_socket_path()

    def test_requires_root_executor_peer(self) -> None:
        peer = MagicMock()
        peer.getsockopt.return_value = struct.pack("3i", 123, 1000, 456)
        with self.assertRaises(ConnectionError):
            ExternalActionSocketClient._verify_peer(peer)

    def test_rejects_invalid_client_configuration(self) -> None:
        for path, timeout in (
            ("relative.sock", 5),
            ("/tmp/test.sock", 0),
            ("/tmp/test.sock", 431),
        ):
            with self.subTest(path=path, timeout=timeout), self.assertRaises(ValueError):
                ExternalActionSocketClient(path, timeout)

    def test_sanitizes_untrusted_response_text_for_display(self) -> None:
        self.assertEqual(
            safe_display_text("SUCCESS\x1b[2J\u202eFAILED"),
            "SUCCESS[2JFAILED",
        )


class YantraMainWindowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_native_shell_builds_required_regions(self) -> None:
        window = YantraMainWindow()
        try:
            self.assertGreaterEqual(window.minimumWidth(), 960)
            self.assertGreaterEqual(window.minimumHeight(), 640)
            for object_name in (
                "topBar",
                "sidebar",
                "terminal",
                "transcriptScroll",
                "composerFrame",
                "rightRail",
                "footer",
            ):
                self.assertIsNotNone(window.findChild(QWidget, object_name))
        finally:
            window.close()

    def test_transcript_api_adds_entries(self) -> None:
        window = YantraMainWindow()
        try:
            before = window.transcript_layout.count()
            window.append_user_message("Open Telegram")
            window.append_executor_message("Rejected", status="error")
            self.assertEqual(window.transcript_layout.count(), before + 2)
        finally:
            window.close()

    def test_worker_reports_connection_drop_without_raising(self) -> None:
        client = MagicMock()
        client.execute.side_effect = ConnectionResetError("peer dropped")
        worker = ExternalActionWorker(client, "Open Telegram")
        failures = []
        worker.failed.connect(failures.append)
        worker.run()
        self.assertEqual(failures, ["peer dropped"])


if __name__ == "__main__":
    unittest.main()
