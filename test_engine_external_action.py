"""Focused tests for typed Kriya action routing and its shared breaker."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from core.engine import KriyaLoopEngine, KriyaState


class _SandboxResult:
    def __init__(self, exit_code: int = 0, stderr: str = "") -> None:
        outcome_value = "SUCCESS" if exit_code == 0 else "FAILED"
        self.outcome = type("Outcome", (), {"value": outcome_value})()
        self.exit_code = exit_code
        self.duration_secs = 0.1
        self.stdout = "healthy" if exit_code == 0 else ""
        self.stderr = stderr


class _Sandbox:
    def __init__(self, result: _SandboxResult | None = None) -> None:
        self.is_operational = True
        self.execute = AsyncMock(return_value=result)


class EngineExternalActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = KriyaLoopEngine.__new__(KriyaLoopEngine)
        self.engine._state = KriyaState()

    async def test_external_action_is_rejected_without_any_execution(self) -> None:
        action_payload = {"action": "open_url", "url": "https://example.com"}
        self.engine._state.pending_actions.append({
            "type": "EXTERNAL_ACTION",
            "reason": "Open the requested page",
            "action_payload": action_payload,
        })
        sandbox = _Sandbox()

        with patch("core.engine.sandbox", sandbox):
            await self.engine._phase_act()

        sandbox.execute.assert_not_awaited()
        self.assertEqual(self.engine._state.consecutive_failures, 1)

    async def test_reason_queues_known_file_fast_path_without_inference(self) -> None:
        self.engine._pending_injections = [
            'Create a file called yc-demo.txt with content "Hello YC"'
        ]
        self.engine._injection_retry_count = 2

        with (
            patch("core.engine.stream_complete") as stream_complete,
            self.assertLogs("yantra.engine", level="INFO") as captured,
        ):
            await self.engine._phase_reason()

        stream_complete.assert_not_called()
        self.assertEqual(self.engine._pending_injections, [])
        self.assertEqual(self.engine._injection_retry_count, 0)
        self.assertEqual(len(self.engine._state.pending_actions), 1)
        action = self.engine._state.pending_actions[0]
        self.assertEqual(action["type"], "EXTERNAL_ACTION")
        self.assertEqual(action["_origin"], "operator")
        self.assertEqual(action["action_payload"], {
            "action": "file_management",
            "operation": "create",
            "path": "yc-demo.txt",
            "content": "Hello YC",
        })
        route_log = "\n".join(captured.output)
        self.assertIn("CLI_FAST_PATH selected", route_log)
        self.assertIn("screenshot loop will be skipped", route_log)

    async def test_reason_logs_computer_use_when_no_app_command_matches(self) -> None:
        self.engine._pending_injections = [
            "Computer use: click the Wi-Fi icon"
        ]
        self.engine._injection_retry_count = 0

        with self.assertLogs("yantra.engine", level="INFO") as captured:
            await self.engine._phase_reason()

        action = self.engine._state.pending_actions[0]
        self.assertEqual(
            action["action_payload"]["instruction"], "click the Wi-Fi icon"
        )
        route_log = "\n".join(captured.output)
        self.assertIn("COMPUTER_USE selected", route_log)
        self.assertIn("screenshot loop is required", route_log)

    async def test_operator_external_success_resets_shared_breaker(self) -> None:
        payload = {
            "action": "file_management",
            "operation": "create",
            "path": "yc-demo.txt",
            "content": "Hello YC",
        }
        self.engine._state.consecutive_failures = 3
        self.engine._state.pending_actions.append({
            "type": "EXTERNAL_ACTION",
            "reason": "known fast path",
            "action_payload": payload,
            "_origin": "operator",
        })
        sandbox = _Sandbox()

        with (
            patch("core.engine.sandbox", sandbox),
            patch("core.engine.run_external_action", return_value=0) as dispatch,
        ):
            await self.engine._phase_act()

        dispatch.assert_called_once_with(payload)
        sandbox.execute.assert_not_awaited()
        self.assertEqual(self.engine._state.consecutive_failures, 0)

    async def test_operator_external_failure_trips_shared_breaker(self) -> None:
        self.engine._state.consecutive_failures = 4
        self.engine._state.conversation_history = [
            {"role": "system", "content": "cognitive context"}
        ]
        self.engine._state.pending_actions.append({
            "type": "EXTERNAL_ACTION",
            "reason": "known fast path",
            "action_payload": {
                "action": "file_management",
                "operation": "move",
                "path": "before.txt",
                "destination": "after.txt",
            },
            "_origin": "operator",
        })

        with patch("core.engine.run_external_action", return_value=1):
            await self.engine._phase_act()

        self.assertEqual(self.engine._state.consecutive_failures, 0)
        self.assertEqual(self.engine._state.conversation_history, [])

    async def test_system_health_script_still_uses_sandbox(self) -> None:
        self.engine._state.pending_actions.append({
            "type": "SANDBOX_SCRIPT",
            "reason": "Low disk space",
            "script": "du -sh /tmp",
        })
        sandbox = _Sandbox(_SandboxResult())

        with (
            patch("core.engine.sandbox", sandbox),
            patch("core.engine.log_action", return_value=True),
            patch("core.engine.log_execution"),
        ):
            await self.engine._phase_act()

        sandbox.execute.assert_awaited_once_with("du -sh /tmp")

    async def test_repeated_sandbox_failures_trip_circuit_breaker(self) -> None:
        self.engine._state.consecutive_failures = 3
        self.engine._state.conversation_history = [
            {"role": "system", "content": "cognitive context"}
        ]
        self.engine._state.pending_actions.extend([
            {
                "type": "SANDBOX_SCRIPT",
                "reason": "Sandbox failure",
                "script": "false",
            },
            {
                "type": "SANDBOX_SCRIPT",
                "reason": "Second sandbox failure",
                "script": "false",
            },
        ])
        sandbox = _Sandbox(_SandboxResult(exit_code=1, stderr="sandbox failed"))

        with (
            patch("core.engine.sandbox", sandbox),
            patch("core.engine.log_action", return_value=True),
            patch("core.engine.log_execution"),
        ):
            await self.engine._phase_act()

        self.assertEqual(self.engine._state.consecutive_failures, 0)
        self.assertEqual(self.engine._state.conversation_history, [])


if __name__ == "__main__":
    unittest.main()
