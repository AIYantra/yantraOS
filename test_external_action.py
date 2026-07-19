"""Root rejection and unprivileged external-action security tests."""

from __future__ import annotations

import os
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import foundry_action_bridge as bridge
from core import host_executor


def address_info(address: str):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]


class RootExternalActionTests(unittest.TestCase):
    def test_external_action_is_not_a_root_intent_and_has_no_bridge_path(self) -> None:
        self.assertNotIn("EXTERNAL_ACTION", host_executor._VALID_INTENTS)
        self.assertFalse(hasattr(host_executor, "_execute_external_action"))
        self.assertFalse(hasattr(host_executor, "_validate_external_action_payload"))
        self.assertFalse(hasattr(host_executor, "_issue_confirmation_challenge"))

    def test_root_rejects_external_action_before_snapshot_or_subprocess(self) -> None:
        payload = {
            "intent": "EXTERNAL_ACTION",
            "target": "",
            "action_payload": {
                "action": "computer_use_task",
                "instruction": "Open settings",
            },
            "confirmation": {"token": "a" * 64, "approved": True},
        }
        with (
            patch.object(host_executor, "_execute_preflight_snapshot") as snapshot,
            patch.object(host_executor.subprocess, "run") as run,
        ):
            result = host_executor._process_intent(payload)

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("never launches", result["error"])
        snapshot.assert_not_called()
        run.assert_not_called()


class FoundryUrlTests(unittest.TestCase):
    def test_browser_actions_require_explicit_secure_opt_in(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(PermissionError):
            bridge._require_browser_enabled()
        with patch.dict(
            os.environ, {"YANTRA_ENABLE_UNPRIVILEGED_BROWSER": "1"}, clear=True
        ), self.assertRaises(PermissionError):
            bridge._require_browser_enabled()

    @patch.object(bridge.socket, "getaddrinfo", return_value=address_info("93.184.216.34"))
    def test_public_http_url_is_allowed(self, _resolve) -> None:
        self.assertEqual(
            bridge._validate_url("https://example.com/path?q=1"),
            "https://example.com/path?q=1",
        )

    def test_credentials_fragments_and_non_http_schemes_are_rejected(self) -> None:
        for url in (
            "https://user:pass@example.com/",
            "https://example.com/#secret",
            "file:///etc/passwd",
            "http://example.com\\@127.0.0.1/",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                bridge._validate_url(url)

    def test_every_non_global_resolution_is_rejected(self) -> None:
        for address in (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
            "192.0.2.1",
            "::1",
            "fc00::1",
            "fe80::1",
        ):
            with (
                self.subTest(address=address),
                patch.object(bridge.socket, "getaddrinfo", return_value=address_info(address)),
                self.assertRaisesRegex(ValueError, "non-global"),
            ):
                bridge._validate_url("https://example.test/")

    def test_private_redirect_is_blocked_before_request_continues(self) -> None:
        class Route:
            def __init__(self, url: str) -> None:
                self.request = SimpleNamespace(url=url)
                self.aborted = False

            def abort(self, _reason: str) -> None:
                self.aborted = True

            def continue_(self) -> None:
                raise AssertionError("private redirect must not continue")

        class Page:
            url = "https://public.example/"

            def route(self, _pattern: str, handler) -> None:
                self.handler = handler

            def goto(self, _url: str, **_kwargs):
                route = Route("http://127.0.0.1/admin")
                self.handler(route)
                assert route.aborted
                return SimpleNamespace(url=self.url)

        def resolve(host: str, _port: int, **_kwargs):
            return address_info("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34")

        with (
            patch.object(bridge.socket, "getaddrinfo", side_effect=resolve),
            self.assertRaisesRegex(ValueError, "Playwright request blocked"),
        ):
            bridge._guarded_goto(Page(), "https://public.example/")


class FoundryManagedOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.root = Path(self.home.name, "YantraActions")
        self.environment = patch.dict(
            os.environ,
            {"HOME": self.home.name, "YANTRA_ACTION_ROOT": str(self.root)},
            clear=True,
        )
        self.environment.start()
        self.unprivileged = patch.object(bridge, "_require_unprivileged_user")
        self.unprivileged.start()

    def tearDown(self) -> None:
        self.unprivileged.stop()
        self.environment.stop()
        self.home.cleanup()

    def test_hidden_absolute_and_traversal_paths_are_rejected(self) -> None:
        for path in (".hidden", "folder/.hidden", "../escape", "/tmp/file", "a//b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                bridge._validate_path(path)

    def test_write_is_private_exclusive_and_non_overwriting(self) -> None:
        bridge.create_dummy_file("reports/result.txt", "first")
        output = self.root / "reports" / "result.txt"
        self.assertEqual(output.read_text(encoding="utf-8"), "first")
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(FileExistsError, "overwrite"):
            bridge.create_dummy_file("reports/result.txt", "second")
        self.assertEqual(output.read_text(encoding="utf-8"), "first")

    def test_symlink_output_is_not_followed_or_replaced(self) -> None:
        self.root.mkdir(mode=0o700)
        target = Path(self.home.name, "outside.txt")
        target.write_text("sentinel", encoding="utf-8")
        (self.root / "link.txt").symlink_to(target)

        with self.assertRaisesRegex(FileExistsError, "symlink"):
            bridge.create_dummy_file("link.txt", "replacement")
        self.assertTrue((self.root / "link.txt").is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "sentinel")

    def test_exact_action_schema_rejects_extra_keys(self) -> None:
        with (
            patch.object(bridge.socket, "getaddrinfo", return_value=address_info("93.184.216.34")),
            self.assertRaisesRegex(ValueError, "schema"),
        ):
            bridge._validate_intent({
                "action": "open_url",
                "url": "https://example.com",
                "command": "ignored",
            })

    def test_uid_zero_is_refused(self) -> None:
        self.unprivileged.stop()
        try:
            with patch.object(bridge.os, "geteuid", return_value=0), self.assertRaises(
                PermissionError
            ):
                bridge._require_unprivileged_user()
        finally:
            self.unprivileged.start()


if __name__ == "__main__":
    unittest.main()
