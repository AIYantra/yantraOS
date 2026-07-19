"""CLI-facing expectations for disabled root external actions."""

import unittest
from unittest.mock import patch

from core import yantra_core


class NaturalLanguageExternalCommandTests(unittest.TestCase):
    def test_cli_treats_root_external_rejection_as_failure_without_challenge(self):
        action = {
            "action": "file_management",
            "operation": "create",
            "path": "plain-english.md",
            "content": "hello\n",
        }
        with patch.object(
            yantra_core,
            "_send_host_request",
            return_value={
                "status": "REJECTED",
                "intent": "EXTERNAL_ACTION",
                "error": "Root Host Executor never launches user-file bridges.",
            },
        ) as send:
            self.assertFalse(yantra_core._execute_host_action(action))
        send.assert_called_once_with(action)

    @patch.object(yantra_core, "_execute_host_action", return_value=False)
    @patch.object(yantra_core.subprocess, "run")
    def test_rejected_file_action_has_no_direct_or_privileged_fallback(self, run, execute):
        actions = [
            {"action": "file_management", "operation": "read", "path": "notes.md"},
            {"action": "computer_use_task", "instruction": "Send notes.md"},
        ]
        yantra_core.execute_actions(actions)
        execute.assert_called_once_with(actions[0])
        run.assert_not_called()

    @patch.object(yantra_core, "_execute_host_action", return_value=False)
    @patch.object(yantra_core.subprocess, "run")
    def test_rejected_computer_use_has_no_direct_bridge_fallback(self, run, execute):
        action = {"action": "computer_use_task", "instruction": "Open Telegram"}
        yantra_core.execute_actions([action])
        execute.assert_called_once_with(action)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
