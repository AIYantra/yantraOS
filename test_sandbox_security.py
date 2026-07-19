"""Focused security tests for the sandbox client, broker, and backend."""

from __future__ import annotations

import asyncio
import json
import stat
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from core.engine import (
    KriyaLoopEngine,
    KriyaState,
    _validated_model_action,
)
from core.sandbox import (
    ExecOutcome as BackendOutcome,
    MAX_OUTPUT_BYTES,
    SANDBOX_IMAGE,
    SandboxEngine,
    SandboxStatus as BackendStatus,
)
from core.sandbox_broker import (
    MAX_REQUEST_BYTES,
    RequestError,
    SandboxBroker,
    _decode_request,
    _read_bounded_request,
)
from core.sandbox_client import (
    BrokerSecurityError,
    ExecOutcome,
    SandboxClient,
    SandboxResult,
    SandboxStatus,
)


class _UnavailableSandbox:
    def __init__(self) -> None:
        self.is_operational = False
        self.status = SandboxStatus.DEGRADED
        self.execute = AsyncMock(return_value=SandboxResult(
            outcome=ExecOutcome.DOCKER_ERROR,
            error="broker unavailable",
        ))
        self.cleanup_stale_containers = AsyncMock(return_value=0)


class EngineFailClosedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = KriyaLoopEngine.__new__(KriyaLoopEngine)
        self.engine._state = KriyaState()

    async def test_degraded_sandbox_fails_closed_and_records_failure(self) -> None:
        self.engine._state.pending_actions.append({
            "type": "SANDBOX_SCRIPT",
            "reason": "diagnostic",
            "script": "echo test",
            "_origin": "model",
        })
        sandbox = _UnavailableSandbox()

        with (
            patch("core.engine.sandbox", sandbox),
            patch("core.engine.log_action", return_value=True),
            patch("core.engine.log_execution") as audit,
        ):
            await self.engine._phase_act()

        sandbox.execute.assert_awaited_once_with("echo test")
        self.assertFalse(hasattr(self.engine, "_send_host_intent"))
        audit.assert_called_once()
        self.assertEqual(self.engine._state.consecutive_failures, 1)
        self.assertIn("Task Failed", self.engine._state.notifications[-1])

    async def test_model_privileged_action_is_rejected_during_act(self) -> None:
        self.engine._state.pending_actions.append({
            "type": "SYSTEM_UPDATE",
            "reason": "model requested host mutation",
            "script": "pacman -Syu",
            "_origin": "model",
        })
        sandbox = _UnavailableSandbox()

        with patch("core.engine.sandbox", sandbox):
            await self.engine._phase_act()

        sandbox.execute.assert_not_awaited()
        self.assertEqual(self.engine._state.consecutive_failures, 1)

    def test_model_schema_rejects_external_and_privileged_types(self) -> None:
        for action_type in ("EXTERNAL_ACTION", "BLOCK_IP", "SYSTEM_UPDATE"):
            with self.subTest(action_type=action_type):
                with self.assertRaises(ValueError):
                    _validated_model_action({
                        "type": action_type,
                        "script": "true",
                    })


class _PeerSocket:
    def __init__(self, uid: int) -> None:
        self.uid = uid

    def getsockopt(self, _level: int, _option: int, _size: int) -> bytes:
        return struct.pack("3i", 123, self.uid, 456)


class _Writer:
    def __init__(self, peer_uid: int) -> None:
        self.peer_socket = _PeerSocket(peer_uid)
        self.payload = b""
        self.closed = False

    def get_extra_info(self, name: str):
        return self.peer_socket if name == "socket" else None

    def write(self, payload: bytes) -> None:
        self.payload += payload

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class BrokerBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_broker_rejects_any_uid_except_yantra_daemon(self) -> None:
        broker = SandboxBroker.__new__(SandboxBroker)
        broker._authorized_uid = 1000
        broker._sandbox = SimpleNamespace(execute=AsyncMock())
        writer = _Writer(peer_uid=1001)

        await broker._handle_client(SimpleNamespace(), writer)

        broker._sandbox.execute.assert_not_awaited()
        self.assertTrue(writer.closed)
        self.assertEqual(writer.payload, b"")

    async def test_wire_oversize_is_rejected_before_json_parsing(self) -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(b"x" * (MAX_REQUEST_BYTES + 1))
        reader.feed_eof()

        with self.assertRaises(RequestError):
            await _read_bounded_request(reader)

    def test_malformed_extra_and_oversized_script_requests_are_rejected(self) -> None:
        bad_requests = (
            b"not-json\n",
            b'{"script":"true","timeout":120}\n',
            b'{"script":"true","script":"id"}\n',
            b'{"script":"true"}\n{"script":"id"}\n',
            json.dumps({"script": "x" * 65_537}).encode("utf-8") + b"\n",
        )
        for request in bad_requests:
            with self.subTest(request=request[:40]):
                with self.assertRaises(RequestError):
                    _decode_request(request)


class ClientPeerVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_rejects_non_root_socket_owner(self) -> None:
        client = SandboxClient("/run/test-broker.sock")
        socket_info = SimpleNamespace(
            st_mode=stat.S_IFSOCK | 0o660,
            st_uid=1000,
        )

        with (
            patch("core.sandbox_client.os.stat", return_value=socket_info),
            patch(
                "core.sandbox_client.asyncio.open_unix_connection",
                new=AsyncMock(),
            ) as connect,
        ):
            status = await client.initialize()

        self.assertEqual(status, SandboxStatus.DEGRADED)
        connect.assert_not_awaited()

    async def test_client_rejects_non_root_connected_peer(self) -> None:
        client = SandboxClient("/run/test-broker.sock")
        socket_info = SimpleNamespace(
            st_mode=stat.S_IFSOCK | 0o660,
            st_uid=0,
        )
        writer = _Writer(peer_uid=1000)

        with (
            patch("core.sandbox_client.os.stat", return_value=socket_info),
            patch(
                "core.sandbox_client.asyncio.open_unix_connection",
                new=AsyncMock(return_value=(SimpleNamespace(), writer)),
            ),
        ):
            with self.assertRaises(BrokerSecurityError):
                await client._open_verified()

        self.assertTrue(writer.closed)


class _LogConfig:
    def __init__(self, *, type: str, config: dict[str, str]) -> None:
        self.type = type
        self.config = config


class _Container:
    def __init__(
        self,
        *,
        status: str,
        stdout: bytes = b"",
        stderr: bytes = b"",
        exit_code: int = 0,
        remove_error: bool = False,
    ) -> None:
        self.id = "container-id"
        self.status = status
        self.attrs = {"State": {"ExitCode": exit_code}}
        self.stdout = stdout
        self.stderr = stderr
        self.kill_calls = 0
        self.remove_calls: list[bool] = []
        self.remove_error = remove_error
        self.started = False

    def start(self) -> None:
        self.started = True

    def reload(self) -> None:
        pass

    def kill(self) -> None:
        self.kill_calls += 1

    def remove(self, *, force: bool) -> None:
        self.remove_calls.append(force)
        if self.remove_error:
            raise RuntimeError("remove failed")

    def logs(self, *, stdout: bool, stderr: bool, **_kwargs):
        return iter([self.stdout if stdout and not stderr else self.stderr])


class _Containers:
    def __init__(self, container: _Container) -> None:
        self.container = container
        self.create_kwargs: dict | None = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return self.container


class _DockerClient:
    def __init__(self, container: _Container) -> None:
        self.containers = _Containers(container)

    def close(self) -> None:
        pass


def _backend_for(container: _Container) -> tuple[SandboxEngine, _DockerClient]:
    backend = SandboxEngine()
    client = _DockerClient(container)
    backend._client = client
    backend._docker = SimpleNamespace(
        types=SimpleNamespace(LogConfig=_LogConfig)
    )
    backend._status = BackendStatus.HEALTHY
    return backend, client


class DockerLifecycleTests(unittest.TestCase):
    def test_timeout_kills_and_force_removes_retained_container(self) -> None:
        container = _Container(status="running")
        backend, client = _backend_for(container)
        self.addCleanup(backend.shutdown)

        with (
            patch("core.sandbox.time.monotonic", side_effect=[0.0, 11.0, 11.0]),
            patch("core.sandbox.time.sleep") as sleep,
        ):
            result = backend._blocking_execute("sleep 99", "hash")

        self.assertEqual(result.outcome, BackendOutcome.TIMEOUT)
        self.assertEqual(result.container_id, "container-id")
        self.assertGreaterEqual(container.kill_calls, 2)
        self.assertEqual(container.remove_calls, [True])
        sleep.assert_not_called()

        settings = client.containers.create_kwargs
        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertEqual(settings["image"], SANDBOX_IMAGE)
        self.assertEqual(settings["network_mode"], "none")
        self.assertTrue(settings["read_only"])
        self.assertEqual(settings["cap_drop"], ["ALL"])
        self.assertEqual(settings["user"], "nobody")
        self.assertFalse(settings["privileged"])
        self.assertEqual(settings["log_config"].config["max-size"], "1m")
        self.assertEqual(settings["log_config"].config["max-file"], "1")

    def test_stdout_and_stderr_are_capped_independently(self) -> None:
        container = _Container(
            status="exited",
            stdout=b"a" * (MAX_OUTPUT_BYTES + 100),
            stderr=b"b" * (MAX_OUTPUT_BYTES + 200),
        )
        backend, _client = _backend_for(container)
        self.addCleanup(backend.shutdown)

        with patch(
            "core.sandbox.time.monotonic", side_effect=[0.0, 0.1]
        ):
            result = backend._blocking_execute("true", "hash")

        self.assertEqual(result.outcome, BackendOutcome.SUCCESS)
        self.assertEqual(len(result.stdout.encode("utf-8")), MAX_OUTPUT_BYTES)
        self.assertEqual(len(result.stderr.encode("utf-8")), MAX_OUTPUT_BYTES)
        self.assertEqual(container.remove_calls, [True])

    def test_cleanup_failure_cannot_be_reported_as_success(self) -> None:
        container = _Container(status="exited", remove_error=True)
        backend, _client = _backend_for(container)
        self.addCleanup(backend.shutdown)

        with patch(
            "core.sandbox.time.monotonic", side_effect=[0.0, 0.1, 0.2]
        ):
            result = backend._blocking_execute("true", "hash")

        self.assertEqual(result.outcome, BackendOutcome.DOCKER_ERROR)
        self.assertEqual(backend.status, BackendStatus.DEGRADED)
        self.assertIn("cleanup failed", result.error or "")

    def test_log_read_failure_cannot_be_reported_as_success(self) -> None:
        container = _Container(status="exited")
        backend, _client = _backend_for(container)
        self.addCleanup(backend.shutdown)
        with (
            patch.object(container, "logs", side_effect=RuntimeError("log failure")),
            patch("core.sandbox.time.monotonic", side_effect=[0.0, 0.1, 0.2]),
        ):
            result = backend._blocking_execute("true", "hash")
        self.assertEqual(result.outcome, BackendOutcome.DOCKER_ERROR)
        self.assertEqual(container.remove_calls, [True])


if __name__ == "__main__":
    unittest.main()
