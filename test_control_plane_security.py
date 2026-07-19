"""Focused security tests for the HTTP, Telegram, and cloud control planes."""

from __future__ import annotations

import asyncio
import os
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import types
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import cloud, telegram_gateway
from core.ipc_server import (
    MAX_NOTIFICATION_COUNT,
    MAX_NOTIFICATION_RESPONSE_BYTES,
    MAX_PENDING_INJECTIONS,
    attach_ipc_routes,
)


class ControlPlaneApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "YANTRA_CONTROL_TOKEN": "control-token-0123456789abcdef0123",
                "YANTRA_DEBUG_API": "0",
                "YANTRA_TEST_MODE": "1",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.engine = SimpleNamespace(
            _pending_injections=[],
            _state=SimpleNamespace(
                notifications=[],
                start_time=time.time(),
                iteration=1,
                phase=SimpleNamespace(value="SENSE"),
                active_model="model",
                inference_routing="LOCAL",
                cpu_pct=1.0,
                disk_free_gb=2.0,
                vram_used_gb=3.0,
                vram_total_gb=4.0,
                gpu_util_pct=5.0,
                consecutive_failures=0,
                blocked_ips=[],
                thought_stream=[],
            ),
            _running=True,
            compliance_executor=MagicMock(),
        )
        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        attach_ipc_routes(app, self.engine)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.auth = {"Host": "localhost", "Authorization": "Bearer control-token-0123456789abcdef0123"}

    def test_missing_and_wrong_bearer_are_rejected(self) -> None:
        missing = self.client.post(
            "/inject", headers={"Host": "localhost"}, json={"command": "status"}
        )
        wrong = self.client.post(
            "/inject",
            headers={"Host": "localhost", "Authorization": "Bearer wrong"},
            json={"command": "status"},
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(self.engine._pending_injections, [])

    def test_missing_server_token_fails_closed_but_health_stays_public(self) -> None:
        with patch.dict(os.environ, {"YANTRA_TEST_MODE": "1"}, clear=True):
            app = FastAPI()

            @app.get("/health")
            async def health():
                return {"status": "ok"}

            attach_ipc_routes(app, self.engine)
            with TestClient(app) as client:
                protected = client.post(
                    "/inject", headers={"Host": "localhost"}, json={"command": "status"}
                )
                health_response = client.get("/health", headers={"Host": "attacker.example"})

        self.assertEqual(protected.status_code, 503)
        self.assertEqual(health_response.status_code, 200)

    def test_non_local_host_and_origin_are_rejected(self) -> None:
        bad_host = self.client.post(
            "/inject",
            headers={"Host": "attacker.example", "Authorization": "Bearer control-token-0123456789abcdef0123"},
            json={"command": "status"},
        )
        bad_origin = self.client.post(
            "/inject",
            headers={**self.auth, "Origin": "https://attacker.example"},
            json={"command": "status"},
        )
        local_origin = self.client.post(
            "/inject",
            headers={**self.auth, "Origin": "http://[::1]:50000"},
            json={"command": "status"},
        )

        self.assertEqual(bad_host.status_code, 403)
        self.assertEqual(bad_origin.status_code, 403)
        self.assertEqual(local_origin.status_code, 200)

    def test_inject_rejects_oversized_control_and_extra_input(self) -> None:
        oversized = self.client.post(
            "/inject", headers=self.auth, json={"command": "x" * 501}
        )
        control = self.client.post(
            "/inject", headers=self.auth, json={"command": "first\nsecond"}
        )
        extra = self.client.post(
            "/inject",
            headers=self.auth,
            json={"command": "status", "instruction": "smuggled"},
        )

        self.assertEqual(oversized.status_code, 422)
        self.assertEqual(control.status_code, 422)
        self.assertEqual(extra.status_code, 422)

    def test_injection_queue_is_capped(self) -> None:
        self.engine._pending_injections[:] = ["queued"] * MAX_PENDING_INJECTIONS

        response = self.client.post(
            "/inject", headers=self.auth, json={"command": "one more"}
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(self.engine._pending_injections), MAX_PENDING_INJECTIONS)

    def test_notification_get_does_not_consume_and_post_is_bounded(self) -> None:
        self.engine._state.notifications[:] = ["x" * 10_000] * (MAX_NOTIFICATION_COUNT + 2)

        get_response = self.client.get("/notifications", headers=self.auth)

        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(
            len(self.engine._state.notifications), MAX_NOTIFICATION_COUNT + 2
        )

        post_response = self.client.post("/notifications", headers=self.auth)

        self.assertEqual(post_response.status_code, 200)
        self.assertLessEqual(
            len(post_response.json()["notifications"]), MAX_NOTIFICATION_COUNT
        )
        self.assertLessEqual(len(post_response.content), MAX_NOTIFICATION_RESPONSE_BYTES)
        self.assertEqual(
            len(self.engine._state.notifications)
            + len(post_response.json()["notifications"]),
            MAX_NOTIFICATION_COUNT + 2,
        )

    def test_debug_is_disabled_without_explicit_flag(self) -> None:
        response = self.client.get("/debug", headers=self.auth)
        self.assertEqual(response.status_code, 403)

    def test_snapper_process_is_killed_on_timeout(self) -> None:
        process = SimpleNamespace(
            communicate=AsyncMock(
                side_effect=[asyncio.TimeoutError, (b"", b"")]
            ),
            kill=MagicMock(),
            returncode=None,
        )
        with patch(
            "core.ipc_server.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ):
            response = self.client.get("/state", headers=self.auth)

        self.assertEqual(response.status_code, 200)
        process.kill.assert_called_once_with()
        self.assertEqual(process.communicate.await_count, 2)

    def test_obsolete_mutation_routes_are_absent(self) -> None:
        for path in ("/api/v1/config/route", "/api/v1/secrets/update"):
            with self.subTest(path=path):
                response = self.client.post(path, headers=self.auth, json={})
                self.assertEqual(response.status_code, 404)


class TelegramGatewayTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _message(chat_type: str, chat_id: int, user_id: int) -> types.Message:
        return types.Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=types.Chat(id=chat_id, type=chat_type),
            from_user=types.User(id=user_id, is_bot=False, first_name="Operator"),
            text="/report",
        )

    async def test_group_message_is_rejected_even_for_operator(self) -> None:
        handler = AsyncMock()
        middleware = telegram_gateway.OperatorOnlyMiddleware()
        with (
            patch.object(telegram_gateway, "OPERATOR_ID", 42),
            patch.object(telegram_gateway, "PRIVATE_CHAT_ID", 42),
        ):
            await middleware(handler, self._message("group", 42, 42), {})

        handler.assert_not_awaited()

    async def test_private_chat_id_must_equal_operator_id(self) -> None:
        handler = AsyncMock(return_value="accepted")
        middleware = telegram_gateway.OperatorOnlyMiddleware()
        with (
            patch.object(telegram_gateway, "OPERATOR_ID", 42),
            patch.object(telegram_gateway, "PRIVATE_CHAT_ID", 42),
        ):
            result = await middleware(
                handler, self._message("private", 42, 42), {}
            )

        self.assertEqual(result, "accepted")
        handler.assert_awaited_once()

    def test_engine_session_sets_bearer_header(self) -> None:
        with (
            patch.object(telegram_gateway, "CONTROL_TOKEN", "control-token-0123456789abcdef0123"),
            patch.object(telegram_gateway.aiohttp, "ClientSession") as session,
        ):
            telegram_gateway._engine_session()

        session.assert_called_once_with(
            headers={"Authorization": "Bearer control-token-0123456789abcdef0123"}
        )

    def test_startup_requires_control_token(self) -> None:
        with (
            patch.object(telegram_gateway, "TOKEN", "bot-token"),
            patch.object(telegram_gateway, "_OPERATOR_ID", "42"),
            patch.object(telegram_gateway, "OPERATOR_ID", 42),
            patch.object(telegram_gateway, "PRIVATE_CHAT_ID", 42),
            patch.object(telegram_gateway, "CONTROL_TOKEN", None),
        ):
            with self.assertRaises(RuntimeError):
                telegram_gateway._validate_configuration()

    def test_task_and_model_text_are_bounded(self) -> None:
        self.assertFalse(
            telegram_gateway._valid_argument(
                "x" * (telegram_gateway.TASK_MAX_LENGTH + 1),
                telegram_gateway.TASK_MAX_LENGTH,
            )
        )
        self.assertEqual(
            len(
                telegram_gateway._bounded_text(
                    "m" * 1000, telegram_gateway.MODEL_MAX_LENGTH
                )
            ),
            telegram_gateway.MODEL_MAX_LENGTH,
        )


class _FakeContent:
    def __init__(self) -> None:
        self.read_limits: list[int] = []

    async def read(self, limit: int) -> bytes:
        self.read_limits.append(limit)
        return b"remote response containing telemetry-secret"


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.content = _FakeContent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeSession:
    def __init__(self, response: _FakeResponse, capture: dict, **kwargs) -> None:
        self.response = response
        self.capture = capture
        self.capture["session"] = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def post(self, url, **kwargs):
        self.capture["url"] = url
        self.capture["post"] = kwargs
        return self.response


class CloudTelemetryTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _state():
        return SimpleNamespace(
            shutdown_requested=False,
            phase=SimpleNamespace(value="SENSE"),
            vram_total_gb=8.0,
            vram_used_gb=2.0,
            active_model="model",
            cpu_pct=10.0,
            ram_percent=20.0,
            thought_stream=[],
        )

    def test_plain_http_requires_exact_loopback(self) -> None:
        self.assertEqual(
            cloud._validate_telemetry_endpoint("http://127.0.0.1:3000/heartbeat"),
            "http://127.0.0.1:3000/heartbeat",
        )
        for endpoint in (
            "http://telemetry.example/heartbeat",
            "ftp://telemetry.example/heartbeat",
            "https://user:secret@telemetry.example/heartbeat",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                cloud._validate_telemetry_endpoint(endpoint)

    async def test_redirect_is_not_followed_and_token_is_header_only(self) -> None:
        capture: dict = {}
        response = _FakeResponse(status=302)

        def session_factory(**kwargs):
            return _FakeSession(response, capture, **kwargs)

        state = self._state()
        with (
            patch.dict(
                os.environ,
                {"YANTRA_TELEMETRY_TOKEN": "telemetry-secret", "YANTRA_NODE_ID": "node-01"},
            ),
            patch.object(
                cloud,
                "TELEMETRY_ENDPOINT",
                "https://telemetry.example/heartbeat",
            ),
            patch("aiohttp.ClientSession", side_effect=session_factory),
        ):
            await cloud.stream_telemetry(state)

        self.assertFalse(capture["post"]["allow_redirects"])
        self.assertEqual(
            capture["post"]["headers"],
            {"Authorization": "Bearer telemetry-secret"},
        )
        self.assertNotIn("daemon_key", capture["post"]["json"])
        self.assertNotIn("thought_stream_tail", capture["post"]["json"])
        self.assertEqual(capture["post"]["json"]["node_id"], "node-01")
        self.assertEqual(
            response.content.read_limits, [cloud.MAX_REJECTION_BODY_BYTES]
        )
        self.assertNotIn("telemetry-secret", " ".join(state.thought_stream))
        self.assertNotIn("remote response", " ".join(state.thought_stream))

    async def test_invalid_runtime_endpoint_is_not_requested(self) -> None:
        state = self._state()
        with (
            patch.dict(
                os.environ,
                {"YANTRA_TELEMETRY_TOKEN": "telemetry-secret", "YANTRA_NODE_ID": "node-01"},
            ),
            patch.object(
                cloud,
                "TELEMETRY_ENDPOINT",
                "http://telemetry.example/heartbeat",
            ),
            patch("aiohttp.ClientSession") as session,
        ):
            await cloud.stream_telemetry(state)

        session.assert_not_called()

    async def test_network_error_text_is_not_added_to_thought_context(self) -> None:
        state = self._state()
        with (
            patch.dict(
                os.environ,
                {"YANTRA_TELEMETRY_TOKEN": "telemetry-secret", "YANTRA_NODE_ID": "node-01"},
            ),
            patch.object(
                cloud,
                "TELEMETRY_ENDPOINT",
                "https://telemetry.example/heartbeat",
            ),
            patch(
                "aiohttp.ClientSession",
                side_effect=RuntimeError("raw-network-secret"),
            ),
        ):
            await cloud.stream_telemetry(state)

        thoughts = " ".join(state.thought_stream)
        self.assertNotIn("raw-network-secret", thoughts)
        self.assertNotIn("telemetry-secret", thoughts)


if __name__ == "__main__":
    unittest.main()
