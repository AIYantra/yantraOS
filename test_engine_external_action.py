"""Focused tests for the sandbox-only Kriya ACT boundary."""

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
