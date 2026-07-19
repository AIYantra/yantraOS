"""Regression tests proving root-to-desktop bridge handoff no longer exists."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core import computer_use_bridge
from core import host_executor


class DesktopBridgeHandoffTests(unittest.TestCase):
    def test_host_executor_has_no_desktop_bridge_symbols(self) -> None:
        for name in (
            "_execute_external_action",
            "_resolve_desktop_account",
            "_BRIDGE_SCRIPT",
            "_COMPUTER_USE_BRIDGE_SCRIPT",
        ):
            self.assertFalse(hasattr(host_executor, name), name)

    def test_external_action_rejection_never_starts_a_process(self) -> None:
        with patch.object(host_executor.subprocess, "run") as run:
            result = host_executor._process_intent({
                "intent": "EXTERNAL_ACTION",
                "target": "",
                "action_payload": {
                    "action": "computer_use_task",
                    "instruction": "Open settings",
                },
            })
        self.assertEqual(result["status"], "REJECTED")
        run.assert_not_called()

    def test_computer_bridge_has_no_host_confirmation_bypass(self) -> None:
        self.assertFalse(hasattr(computer_use_bridge, "_launched_by_root_executor"))
        with (
            patch.object(computer_use_bridge.os, "geteuid", return_value=1000),
            patch.object(computer_use_bridge.sys.stdin, "isatty", return_value=False),
            self.assertRaises(RuntimeError),
        ):
            computer_use_bridge._require_interactive_session()


if __name__ == "__main__":
    unittest.main()
