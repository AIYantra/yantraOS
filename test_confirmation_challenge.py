"""Tests for fail-closed local action confirmation and counter storage."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import action_confirmation as confirmation


class ActionConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_counter = confirmation.COUNTER_PATH
        self.temporary = tempfile.TemporaryDirectory()
        confirmation.COUNTER_PATH = str(
            Path(self.temporary.name, "state", "confirmation_counter.json")
        )

    def tearDown(self) -> None:
        confirmation.COUNTER_PATH = self.original_counter
        self.temporary.cleanup()

    def test_run_count_never_self_approves_sensitive_actions(self) -> None:
        confirmation._write_counter(10_000)
        actions = (
            {"action": "open_url", "url": "https://example.com"},
            {"action": "navigate_and_extract", "url": "https://example.com"},
            {"action": "create_dummy_file", "path": "notes.txt"},
            {"action": "file_management", "operation": "move", "path": "a"},
            {"action": "computer_use_task", "instruction": "Open settings"},
        )
        with (
            patch.object(confirmation.sys.stdin, "isatty", return_value=False),
            patch.object(confirmation.audit_log, "log_action"),
        ):
            for action in actions:
                with self.subTest(action=action):
                    self.assertTrue(confirmation.requires_confirmation(action))
                    self.assertFalse(confirmation.confirm_action(action))

    def test_counter_directory_and_file_are_private(self) -> None:
        confirmation._write_counter(7)
        path = Path(confirmation.COUNTER_PATH)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(confirmation._read_counter(), 7)
        self.assertFalse(any(path.parent.glob(".*.tmp")))

    def test_counter_symlink_is_never_followed_or_replaced(self) -> None:
        path = Path(confirmation.COUNTER_PATH)
        path.parent.mkdir(mode=0o700)
        target = Path(self.temporary.name, "target.json")
        target.write_text("sentinel", encoding="utf-8")
        path.symlink_to(target)

        confirmation._write_counter(99)

        self.assertTrue(path.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "sentinel")
        self.assertEqual(confirmation._read_counter(), 0)

    def test_counter_rejects_insecure_mode_on_read(self) -> None:
        confirmation._write_counter(4)
        path = Path(confirmation.COUNTER_PATH)
        path.chmod(0o644)
        self.assertEqual(confirmation._read_counter(), 0)

    def test_confirmation_summary_includes_exact_instruction_and_model_action(self) -> None:
        summary = confirmation._format_action_summary({
            "action": "computer_use_task_step_1",
            "instruction": "Open settings",
            "proposed_action": {"action": "key", "key": "28:1 28:0"},
        })
        self.assertIn("Open settings", summary)
        self.assertIn('"key": "28:1 28:0"', summary)


if __name__ == "__main__":
    unittest.main()
