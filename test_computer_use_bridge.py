import base64
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import computer_use_bridge as bridge

try:
    from PIL import Image
except ImportError:
    Image = None


def encoded_image(color: str) -> str:
    if Image is None:
        return base64.b64encode(color.encode("ascii")).decode("ascii")
    image = Image.new("RGB", (64, 64), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class ScreenshotDetectionTests(unittest.TestCase):
    def test_identical_screens_have_no_difference(self):
        screenshot = encoded_image("black")
        self.assertEqual(bridge.screenshot_difference(screenshot, screenshot), 0.0)

    def test_changed_screens_exceed_threshold(self):
        difference = bridge.screenshot_difference(
            encoded_image("black"), encoded_image("white")
        )
        self.assertGreater(difference, bridge.SCREEN_CHANGE_THRESHOLD)

    def test_two_unchanged_interactive_actions_reach_cutoff(self):
        count = bridge.update_ineffective_count({"action": "click"}, 0.0, 0)
        count = bridge.update_ineffective_count({"action": "key"}, 0.0, count)
        self.assertEqual(count, bridge.MAX_INEFFECTIVE_ACTIONS)

    def test_wait_does_not_increment_cutoff(self):
        count = bridge.update_ineffective_count({"action": "wait"}, 0.0, 1)
        self.assertEqual(count, 1)

    def test_small_focus_or_text_change_resets_cutoff(self):
        count = bridge.update_ineffective_count(
            {"action": "click"}, 0.000577, 1
        )
        self.assertEqual(count, 0)


class ClipboardActionTests(unittest.TestCase):
    @patch("core.computer_use_bridge.subprocess.run")
    def test_copy_text_uses_wl_copy(self, run):
        run.return_value = subprocess.CompletedProcess(["wl-copy"], 0)

        bridge.execute_action({"action": "clipboard_copy", "text": "Meet URL"})

        self.assertEqual(run.call_args.args[0], ["wl-copy"])
        self.assertEqual(run.call_args.kwargs["input"], b"Meet URL")
        self.assertNotIn("AZURE_OPENAI_API_KEY", run.call_args.kwargs["env"])

    @patch("core.computer_use_bridge.subprocess.run")
    def test_paste_checks_clipboard_then_uses_ctrl_v(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(["wl-paste"], 0, stdout=b"Meet URL"),
            subprocess.CompletedProcess(["ydotool"], 0),
        ]

        bridge.execute_action({"action": "clipboard_paste"})

        self.assertEqual(run.call_args_list[0].args[0], ["wl-paste", "--no-newline"])
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
        )

    @patch("core.computer_use_bridge.subprocess.run")
    def test_double_click_emits_two_clicks(self, run):
        run.return_value = subprocess.CompletedProcess(["ydotool"], 0)

        bridge.execute_action({
            "action": "double_click", "x": 100, "y": 80, "button": "left"
        }, img_w=200, img_h=160)

        click_calls = [
            item for item in run.call_args_list
            if item.args[0] == ["ydotool", "click", "0xC0"]
        ]
        self.assertEqual(len(click_calls), 2)


class FileManagementTests(unittest.TestCase):
    @patch.dict(
        "core.computer_use_bridge.os.environ",
        {"AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-5.6-sol"},
        clear=True,
    )
    def test_file_management_uses_sol_and_dolphin_rules(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"action":"done","reason":"read"}'
            ))]
        )

        bridge.get_next_action(
            client,
            "Read /tmp/notes.txt",
            encoded_image("black"),
            [],
            64,
            64,
            task_type="file_management",
        )

        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-5.6-sol")
        self.assertIn("KDE Dolphin", request["messages"][0]["content"])
        self.assertIn(
            "exact visible contents", request["messages"][0]["content"]
        )

    def test_create_is_bounded_non_overwriting_and_written_exclusively(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            bridge.os.environ,
            {
                "HOME": directory,
                "YANTRA_FILE_ROOT": str(Path(directory, "YantraOS")),
            },
            clear=True,
        ):
            instruction = bridge.prepare_file_management({
                "action": "file_management",
                "operation": "create",
                "path": "notes.txt",
                "content": "private contents",
            })
            self.assertNotIn("private contents", instruction)
            created = Path(directory, "YantraOS", "notes.txt")
            self.assertEqual(created.read_text(encoding="utf-8"), "private contents")
            self.assertEqual(created.stat().st_mode & 0o777, 0o600)
            self.assertTrue(bridge.created_file_matches({
                "path": "notes.txt", "content": "private contents"
            }, str(Path(directory, "YantraOS"))))
            created.write_text("changed", encoding="utf-8")
            self.assertFalse(bridge.created_file_matches({
                "path": "notes.txt", "content": "private contents"
            }, str(Path(directory, "YantraOS"))))
            with self.assertRaisesRegex(ValueError, "overwrite"):
                bridge.prepare_file_management({
                    "action": "file_management",
                    "operation": "create",
                    "path": "notes.txt",
                })

    def test_move_fast_path_preserves_content_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            bridge.os.environ,
            {
                "HOME": directory,
                "YANTRA_FILE_ROOT": str(Path(directory, "YantraOS")),
            },
            clear=True,
        ):
            root = Path(directory, "YantraOS")
            root.mkdir()
            source = root / "before.txt"
            source.write_text("unchanged", encoding="utf-8")
            payload = {
                "action": "file_management",
                "operation": "move",
                "path": "before.txt",
                "destination": "archive/after.txt",
            }

            result = bridge.execute_fast_path(payload)

            destination = root / "archive" / "after.txt"
            self.assertFalse(source.exists())
            self.assertEqual(destination.read_text(encoding="utf-8"), "unchanged")
            self.assertIn("without overwrite", result)

            source.write_text("second", encoding="utf-8")
            payload["destination"] = "archive/after.txt"
            with self.assertRaisesRegex(ValueError, "overwrite"):
                bridge.execute_fast_path(payload)
            self.assertEqual(source.read_text(encoding="utf-8"), "second")

    def test_delete_and_escape_paths_are_disabled(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            bridge.os.environ,
            {
                "HOME": directory,
                "YANTRA_FILE_ROOT": str(Path(directory, "YantraOS")),
            },
            clear=True,
        ):
            for payload in (
                {"action": "file_management", "operation": "delete", "path": "notes.txt"},
                {"action": "file_management", "operation": "read", "path": "/etc/passwd"},
                {"action": "file_management", "operation": "read", "path": "../notes.txt"},
                {"action": "file_management", "operation": "read", "path": ".ssh/id_rsa"},
            ):
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    bridge.prepare_file_management(payload)

    def test_destructive_gui_actions_are_blocked_before_ydotool(self):
        blocked = (
            {"action": "click", "x": 10, "y": 10, "button": "right"},
            {"action": "key", "key": "111:1 111:0"},
            {"action": "key", "key": "42:1 111:1 111:0 42:0"},
            {"action": "key", "key": "29:1 38:1 38:0 29:0"},
            {"action": "key", "key": "125:1 125:0"},
            {"action": "clipboard_copy", "text": "replacement"},
        )
        for action in blocked:
            with self.subTest(action=action), self.assertRaises(ValueError):
                bridge.validate_file_management_action(action, img_w=640, img_h=480)

        bridge.validate_file_management_action(
            {"action": "click", "x": 500, "y": 300}, img_w=640, img_h=480
        )
        bridge.validate_file_management_action({"action": "clipboard_paste"})
        bridge.validate_file_management_action({"action": "key", "key": "29:1 30:1 30:0 29:0"})

        with self.assertRaisesRegex(ValueError, "visually verified"):
            bridge.validate_file_management_action(
                {"action": "click", "x": 500, "y": 300},
                "create",
                640,
                480,
            )
        bridge.validate_file_management_action(
            {"action": "key", "key": "63:1 63:0"}, "create"
        )
        bridge.validate_file_management_action(
            {"action": "done", "success": True}, "create"
        )

    def test_managed_root_rejects_escape_and_symlink_then_repairs_owned_mode(self):
        payload = {"action": "file_management", "operation": "read", "path": "notes.txt"}
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as outside:
            with patch.dict(
                bridge.os.environ,
                {"HOME": home, "YANTRA_FILE_ROOT": str(Path(outside, "YantraOS"))},
                clear=True,
            ), self.assertRaisesRegex(ValueError, "inside HOME"):
                bridge.prepare_file_management(payload)

            root = Path(home, "YantraOS")
            root.symlink_to(outside, target_is_directory=True)
            with patch.dict(
                bridge.os.environ,
                {"HOME": home, "YANTRA_FILE_ROOT": str(root)},
                clear=True,
            ), self.assertRaisesRegex(ValueError, "symlink"):
                bridge.prepare_file_management(payload)
            root.unlink()

            root.mkdir(mode=0o777)
            root.chmod(0o777)
            Path(root, "notes.txt").write_text("safe", encoding="utf-8")
            with patch.dict(
                bridge.os.environ,
                {"HOME": home, "YANTRA_FILE_ROOT": str(root)},
                clear=True,
            ):
                bridge.prepare_file_management(payload)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)

            with patch.dict(
                bridge.os.environ,
                {"HOME": home, "YANTRA_FILE_ROOT": str(root)},
                clear=True,
            ), patch.object(bridge.os, "geteuid", return_value=-1), self.assertRaisesRegex(
                ValueError, "foreign ownership"
            ):
                bridge.prepare_file_management(payload)


class ModelActionSchemaTests(unittest.TestCase):
    def test_unknown_actions_and_extra_or_missing_keys_are_rejected(self):
        invalid = (
            {"action": "shell", "command": "id"},
            {"action": "click", "x": 1, "y": 1, "command": "id"},
            {"action": "type"},
            {"action": "clipboard_paste", "text": "extra"},
            {"action": "done", "success": "yes"},
        )
        for action in invalid:
            with self.subTest(action=action), self.assertRaises(ValueError):
                bridge.validate_model_action(action, 100, 100)

    def test_coordinates_must_be_integer_and_inside_current_image(self):
        for action in (
            {"action": "click", "x": -1, "y": 0},
            {"action": "click", "x": 100, "y": 0},
            {"action": "click", "x": 0, "y": 100},
            {"action": "click", "x": True, "y": 1},
            {"action": "click", "x": 1.5, "y": 1},
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                bridge.validate_model_action(action, 100, 100)
        bridge.validate_model_action({"action": "click", "x": 99, "y": 99}, 100, 100)

    def test_text_clipboard_key_and_wait_values_are_bounded(self):
        invalid = (
            {"action": "type", "text": "x" * (bridge.MAX_MODEL_TEXT_BYTES + 1)},
            {"action": "clipboard_copy", "text": "x" * (bridge.MAX_CLIPBOARD_BYTES + 1)},
            {"action": "key", "key": "1:1 " * bridge.MAX_KEY_EVENTS + "1:0"},
            {"action": "key", "key": "not-a-key"},
            {"action": "wait", "seconds": 0},
            {"action": "wait", "seconds": bridge.MAX_WAIT_SECONDS + 1},
            {"action": "done", "reason": "x" * (bridge.MAX_DONE_REASON_CHARS + 1)},
        )
        for action in invalid:
            with self.subTest(action=action), self.assertRaises(ValueError):
                bridge.validate_model_action(action, 100, 100)

    def test_host_confirmation_bypass_is_removed(self):
        self.assertFalse(hasattr(bridge, "_launched_by_root_executor"))
        self.assertNotIn("YANTRA_HOST_CONFIRMED", bridge.__dict__)

    def test_only_explicit_azure_variables_are_accepted(self):
        with patch.dict(bridge.os.environ, {"YANTRA_AZURE_KEY": "legacy"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "AZURE_OPENAI"):
                bridge._azure_configuration()

        expected = ("https://example.test/openai/v1", "deployment", "key")
        with patch.dict(
            bridge.os.environ,
            {
                "AZURE_OPENAI_ENDPOINT": expected[0],
                "AZURE_DEPLOYMENT_LUNA": expected[1],
                "AZURE_OPENAI_DEPLOYMENT_NAME": "fallback-deployment",
                "AZURE_OPENAI_API_KEY": expected[2],
                "AWS_SECRET_ACCESS_KEY": "must-not-leak",
            },
            clear=True,
        ), patch.object(
            bridge.socket,
            "getaddrinfo",
            return_value=[(bridge.socket.AF_INET, bridge.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        ):
            self.assertEqual(bridge._azure_configuration(), expected)
            self.assertNotIn("AZURE_OPENAI_API_KEY", bridge._child_environment())
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", bridge._child_environment())

    def test_headless_session_fails_closed(self):
        with (
            patch.object(bridge.os, "geteuid", return_value=1000),
            patch.object(bridge.sys.stdin, "isatty", return_value=False),
            self.assertRaisesRegex(RuntimeError, "TTY"),
        ):
            bridge._require_interactive_session()


class FastPathRoutingTests(unittest.TestCase):
    def test_long_natural_instruction_allows_punctuation_but_remains_bounded(self):
        instruction = "Complete this draft; save it, but do not submit. " + "x" * 3000
        payload = {"action": "computer_use_task", "instruction": instruction}

        self.assertIs(bridge.validate_task_intent(payload), payload)
        payload["instruction"] = "x" * (bridge.MAX_TASK_INSTRUCTION_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "8192 bytes"):
            bridge.validate_task_intent(payload)

    def test_small_table_selects_files_and_known_apps_only(self):
        fast_tasks = (
            {
                "action": "file_management",
                "operation": "create",
                "path": "notes.txt",
                "content": "hello",
            },
            {
                "action": "file_management",
                "operation": "move",
                "path": "notes.txt",
                "destination": "archive/notes.txt",
            },
            {"action": "computer_use_task", "instruction": "Open Firefox"},
            {
                "action": "computer_use_task",
                "instruction": "Open the Calculator application.",
            },
        )
        for task in fast_tasks:
            with self.subTest(task=task):
                route, reason = bridge.select_task_route(task)
                self.assertEqual(route, "CLI_FAST_PATH")
                self.assertTrue(reason)

        route, reason = bridge.select_task_route({
            "action": "computer_use_task",
            "instruction": "Open Calendar",
        })
        self.assertEqual(route, "COMPUTER_USE")
        self.assertIn("no approved", reason)

        route, reason = bridge.select_task_route({
            "action": "file_management",
            "operation": "read",
            "path": "notes.txt",
        })
        self.assertEqual(route, "REJECTED")
        self.assertIn("disabled", reason)

    @patch("core.computer_use_bridge.time.sleep")
    @patch("core.computer_use_bridge.subprocess.Popen")
    def test_known_app_uses_explicit_argv_without_secrets(self, popen, _sleep):
        popen.return_value.poll.return_value = None
        with patch.dict(
            bridge.os.environ,
            {
                "PATH": "/usr/bin",
                "WAYLAND_DISPLAY": "wayland-0",
                "AZURE_OPENAI_API_KEY": "must-not-leak",
            },
            clear=True,
        ):
            bridge.execute_fast_path({
                "action": "computer_use_task",
                "instruction": "Launch Firefox",
            })

        command = popen.call_args.args[0]
        self.assertEqual(command, ("/usr/bin/firefox",))
        self.assertNotIn("shell", popen.call_args.kwargs)
        self.assertNotIn(
            "AZURE_OPENAI_API_KEY", popen.call_args.kwargs["env"]
        )

    def test_all_fast_paths_skip_azure_and_screenshot_loop(self):
        payloads = (
            {
                "action": "file_management",
                "operation": "create",
                "path": "yc-demo.txt",
                "content": "Hello YC",
            },
            {
                "action": "file_management",
                "operation": "move",
                "path": "before.txt",
                "destination": "after.txt",
            },
            {"action": "computer_use_task", "instruction": "Open Firefox"},
        )
        with (
            patch("core.computer_use_bridge._require_confirmation_session"),
            patch("core.computer_use_bridge._require_app_session"),
            patch("core.action_confirmation.confirm_action", return_value=True),
            patch("core.action_confirmation.log_execution_outcome") as outcome,
            patch("core.computer_use_bridge.execute_fast_path", return_value="created") as execute,
            patch("core.computer_use_bridge._azure_configuration") as azure,
            patch("core.computer_use_bridge.take_screenshot") as screenshot,
            self.assertLogs("yantra.computer_use_bridge", level="INFO") as captured,
        ):
            exit_codes = [bridge.run_intent(payload) for payload in payloads]

        self.assertEqual(exit_codes, [bridge.EXIT_SUCCESS] * len(payloads))
        self.assertEqual(execute.call_count, len(payloads))
        azure.assert_not_called()
        screenshot.assert_not_called()
        self.assertEqual(outcome.call_count, len(payloads))
        self.assertIn("screenshot loop skipped", "\n".join(captured.output))

    def test_fast_path_reports_failure_when_outcome_audit_fails(self):
        payload = {
            "action": "file_management",
            "operation": "create",
            "path": "yc-demo.txt",
            "content": "Hello YC",
        }
        with (
            patch("core.computer_use_bridge._require_confirmation_session"),
            patch("core.action_confirmation.confirm_action", return_value=True),
            patch(
                "core.action_confirmation.log_execution_outcome",
                return_value=False,
            ),
            patch("core.computer_use_bridge.execute_fast_path", return_value="created"),
        ):
            self.assertEqual(bridge.run_intent(payload), bridge.EXIT_ERROR)

    def test_confirmed_create_runs_end_to_end_without_screenshot(self):
        from core import action_confirmation, audit_log

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "YantraOS")
            audit_path = Path(directory, "state", "audit.jsonl")
            counter_path = Path(directory, "state", "counter.json")
            payload = {
                "action": "file_management",
                "operation": "create",
                "path": "yc-demo.txt",
                "content": "Hello YC",
            }
            with (
                patch.dict(
                    bridge.os.environ,
                    {"HOME": directory, "YANTRA_FILE_ROOT": str(root)},
                    clear=True,
                ),
                patch.object(audit_log, "AUDIT_LOG_PATH", str(audit_path)),
                patch.object(action_confirmation, "COUNTER_PATH", str(counter_path)),
                patch.object(bridge.sys.stdin, "isatty", return_value=True),
                patch("builtins.input", return_value="y"),
                patch("core.computer_use_bridge._azure_configuration") as azure,
                patch("core.computer_use_bridge.take_screenshot") as screenshot,
            ):
                exit_code = bridge.run_intent(payload)

            self.assertEqual(exit_code, bridge.EXIT_SUCCESS)
            self.assertEqual(
                Path(root, "yc-demo.txt").read_text(encoding="utf-8"), "Hello YC"
            )
            self.assertGreaterEqual(len(audit_path.read_text().splitlines()), 3)
            azure.assert_not_called()
            screenshot.assert_not_called()

    def test_unknown_task_keeps_computer_use_loop(self):
        payload = {
            "action": "computer_use_task",
            "instruction": "Open Calendar",
        }
        with (
            patch("core.computer_use_bridge._require_interactive_session"),
            patch("core.action_confirmation.confirm_action", return_value=True),
            patch("core.audit_log.log_action", return_value=True),
            patch(
                "core.computer_use_bridge._azure_configuration",
                return_value=("https://example.test", "deployment", "key"),
            ),
            patch("core.computer_use_bridge.OpenAI") as openai,
            patch(
                "core.computer_use_bridge.take_screenshot",
                return_value=(encoded_image("black"), 1.0, 64, 64),
            ) as screenshot,
            patch(
                "core.computer_use_bridge.get_next_action",
                return_value={"action": "done", "reason": "opened"},
            ),
            patch("core.computer_use_bridge.execute_fast_path") as execute,
        ):
            exit_code = bridge.run_intent(payload)

        self.assertEqual(exit_code, bridge.EXIT_SUCCESS)
        self.assertEqual(openai.call_args.kwargs["max_retries"], 2)
        screenshot.assert_called_once()
        execute.assert_not_called()

    def test_step_confirmation_uses_transient_screen_baseline(self):
        payload = {
            "action": "computer_use_task",
            "instruction": "Open Calendar",
        }
        screenshot = encoded_image("black")
        with (
            patch("core.computer_use_bridge._require_interactive_session"),
            patch(
                "core.action_confirmation.confirm_action",
                side_effect=[True, True],
            ) as confirm,
            patch("core.action_confirmation.log_execution_outcome", return_value=True),
            patch("core.audit_log.log_action", return_value=True),
            patch(
                "core.computer_use_bridge._azure_configuration",
                return_value=("https://example.test", "gpt-5.6-luna", "key"),
            ),
            patch("core.computer_use_bridge.OpenAI"),
            patch(
                "core.computer_use_bridge.take_screenshot",
                return_value=(screenshot, 1.0, 64, 64),
            ) as take_screenshot,
            patch(
                "core.computer_use_bridge.get_next_action",
                side_effect=[
                    {"action": "key", "key": "125:1 125:0"},
                    {"action": "done", "reason": "opened"},
                ],
            ),
            patch("core.computer_use_bridge.execute_action") as execute,
            patch("core.computer_use_bridge.time.sleep"),
        ):
            exit_code = bridge.run_intent(payload)

        self.assertEqual(exit_code, bridge.EXIT_SUCCESS)
        execute.assert_called_once()
        self.assertEqual(
            confirm.call_args_list[1].kwargs,
            {"transient": True},
        )
        self.assertEqual(take_screenshot.call_args_list[1].kwargs, {"quiet": True})
        self.assertEqual(take_screenshot.call_args_list[2].kwargs, {"quiet": True})

    def test_step_approval_mode_skips_repeated_prompts_and_stale_checks(self):
        payload = {
            "action": "computer_use_task",
            "instruction": "Open Calendar",
        }
        screenshot = encoded_image("black")
        with (
            patch("core.computer_use_bridge._require_interactive_session"),
            patch(
                "core.action_confirmation.confirm_action",
                side_effect=[True, True],
            ) as confirm,
            patch("core.action_confirmation.log_execution_outcome", return_value=True),
            patch("core.audit_log.log_action", return_value=True),
            patch(
                "core.computer_use_bridge._azure_configuration",
                return_value=("https://example.test", "gpt-5.6-luna", "key"),
            ),
            patch("core.computer_use_bridge.OpenAI"),
            patch(
                "core.computer_use_bridge.take_screenshot",
                return_value=(screenshot, 1.0, 64, 64),
            ) as take_screenshot,
            patch(
                "core.computer_use_bridge.get_next_action",
                side_effect=[
                    {"action": "key", "key": "125:1 125:0"},
                    {"action": "done", "reason": "opened"},
                ],
            ),
            patch("core.computer_use_bridge.execute_action"),
            patch("core.computer_use_bridge.time.sleep"),
        ):
            exit_code = bridge.run_intent(payload, approve_steps=True)

        self.assertEqual(exit_code, bridge.EXIT_SUCCESS)
        self.assertEqual(confirm.call_args_list[1].kwargs, {"preapproved": True})
        self.assertEqual(take_screenshot.call_count, 2)

    @patch.dict(
        "core.computer_use_bridge.os.environ",
        {"AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-5.6-sol"},
        clear=True,
    )
    def test_generic_browser_prompt_does_not_hardcode_telegram(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"action":"done","reason":"found"}'
            ))]
        )

        bridge.get_next_action(
            client,
            "Open Firefox and visually read ycombinator.com",
            encoded_image("black"),
            [],
            64,
            64,
        )

        prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("address bar", prompt)
        self.assertIn("29:1 38:1 38:0 29:0", prompt)
        self.assertIn("Symbolic key names", prompt)
        self.assertNotIn('"text": "Telegram"', prompt)


if __name__ == "__main__":
    unittest.main()
