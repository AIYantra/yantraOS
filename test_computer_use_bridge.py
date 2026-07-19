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
                "AZURE_OPENAI_DEPLOYMENT_NAME": expected[1],
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


if __name__ == "__main__":
    unittest.main()
