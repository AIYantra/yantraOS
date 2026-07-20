"""CLI-facing expectations for unprivileged external actions."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import yantra_core


class NaturalLanguageExternalCommandTests(unittest.TestCase):
    def test_cli_defaults_to_one_task_level_approval(self):
        arguments, approve_steps = yantra_core._parse_cli_arguments(["do", "task"])
        self.assertEqual(arguments, ["do", "task"])
        self.assertTrue(approve_steps)

        arguments, approve_steps = yantra_core._parse_cli_arguments(
            ["--confirm-steps", "do", "task"]
        )
        self.assertEqual(arguments, ["do", "task"])
        self.assertFalse(approve_steps)

    @patch.object(yantra_core, "execute_actions")
    @patch.object(yantra_core, "get_openai_client")
    def test_planner_prefers_luna_deployment(self, get_client, execute):
        get_client.return_value.responses.create.return_value = SimpleNamespace(
            output=[SimpleNamespace(
                type="message",
                content=[SimpleNamespace(
                    type="output_text",
                    text='[{"action":"computer_use_task","instruction":"test"}]',
                )],
            )]
        )
        with patch.dict(
            yantra_core.os.environ,
            {
                "AZURE_DEPLOYMENT_LUNA": "gpt-5.6-luna",
                "AZURE_OPENAI_DEPLOYMENT_NAME": "fallback",
            },
            clear=True,
        ):
            yantra_core.process_query("test")

        request = get_client.return_value.responses.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-5.6-luna")
        execute.assert_called_once()

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

    @patch.object(yantra_core, "run_external_action", return_value=1)
    @patch.object(yantra_core.subprocess, "run")
    def test_failed_file_action_stops_without_privileged_fallback(self, run, execute):
        actions = [
            {"action": "file_management", "operation": "read", "path": "notes.md"},
            {"action": "computer_use_task", "instruction": "Send notes.md"},
        ]
        yantra_core.execute_actions(actions)
        execute.assert_called_once_with(actions[0])
        run.assert_not_called()

    @patch.object(yantra_core, "run_external_action", return_value=0)
    @patch.object(yantra_core.subprocess, "run")
    def test_known_app_uses_unprivileged_session_dispatch(self, run, execute):
        action = {"action": "computer_use_task", "instruction": "Open Firefox"}
        with self.assertLogs("yantra.core", level="INFO") as captured:
            yantra_core.execute_actions([action])
        execute.assert_called_once_with(action)
        run.assert_not_called()
        self.assertIn("CLI_FAST_PATH selected", "\n".join(captured.output))

    @patch.object(yantra_core, "run_external_action", return_value=0)
    def test_step_approval_flag_is_forwarded_to_bridge(self, execute):
        action = {"action": "computer_use_task", "instruction": "Open Calendar"}

        yantra_core.execute_actions([action], approve_steps=True)

        execute.assert_called_once_with(action, approve_steps=True)

    @patch.object(yantra_core, "run_external_action", return_value=0)
    @patch.object(yantra_core.subprocess, "run")
    def test_disabled_browser_api_routes_once_to_computer_use(self, run, execute):
        actions = [
            {"action": "open_url", "url": "https://www.ycombinator.com/"},
            {
                "action": "navigate_and_extract",
                "url": "https://www.ycombinator.com/",
                "instruction": "find the upcoming batch text",
                "output_path": "/tmp/result.txt",
            },
        ]

        yantra_core.execute_actions(actions)

        execute.assert_called_once_with({
            "action": "computer_use_task",
            "instruction": (
                "Open Firefox, go to https://www.ycombinator.com/, "
                "and find the upcoming batch text"
            ),
        })
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
