"""Focused security tests for the privileged Host Executor."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import struct
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import core.host_executor as host_executor


class _PeerSocket:
    def __init__(self, uid: int) -> None:
        self.uid = uid

    def getsockopt(self, _level: int, _option: int, _size: int) -> bytes:
        return struct.pack("3i", 123, self.uid, 456)


class _Reader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.called = False

    async def readline(self) -> bytes:
        self.called = True
        return self.payload


class _Writer:
    def __init__(self, uid: int) -> None:
        self.peer = _PeerSocket(uid)
        self.output = bytearray()
        self.closed = False

    def get_extra_info(self, name: str):
        return self.peer if name == "socket" else None

    def write(self, payload: bytes) -> None:
        self.output.extend(payload)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class HostExecutorSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_unauthorized_peer_is_rejected_before_payload_read(self) -> None:
        reader = _Reader(b'{"intent":"RESTART_DAEMON","target":"yantra.service"}\n')
        writer = _Writer(uid=1001)

        with patch.object(host_executor, "_resolve_authorized_uid", return_value=2001):
            await host_executor._handle_client(reader, writer)

        self.assertFalse(reader.called)
        self.assertTrue(writer.closed)
        response = json.loads(writer.output)
        self.assertEqual(response["status"], "REJECTED")
        self.assertIn("Unauthorized", response["error"])

    async def test_authorized_external_action_is_rejected_without_execution(self) -> None:
        reader = _Reader(
            b'{"intent":"EXTERNAL_ACTION","target":"",'
            b'"action_payload":{"action":"open_url","url":"https://example.com"}}\n'
        )
        writer = _Writer(uid=2001)

        with (
            patch.object(host_executor, "_resolve_authorized_uid", return_value=2001),
            patch.object(host_executor, "_execute_preflight_snapshot") as snapshot,
            patch.object(host_executor.subprocess, "run") as run,
        ):
            await host_executor._handle_client(reader, writer)

        self.assertTrue(reader.called)
        response = json.loads(writer.output)
        self.assertEqual(response["status"], "REJECTED")
        self.assertEqual(response["intent"], "EXTERNAL_ACTION")
        self.assertIn("never launches", response["error"])
        snapshot.assert_not_called()
        run.assert_not_called()


class HostExecutorPolicyTests(unittest.TestCase):
    def test_socket_group_is_explicit_and_not_process_derived(self) -> None:
        with (
            patch.object(
                host_executor.grp,
                "getgrnam",
                return_value=SimpleNamespace(gr_gid=4242),
            ) as getgrnam,
            patch.dict(os.environ, {"SUDO_USER": "attacker"}, clear=True),
            patch.object(host_executor.os, "getgid", side_effect=AssertionError),
        ):
            self.assertEqual(host_executor._resolve_socket_group(), 4242)
        getgrnam.assert_called_once_with("yantra")

    def test_socket_metadata_check_never_follows_or_chowns_path(self) -> None:
        metadata = SimpleNamespace(
            st_mode=stat.S_IFSOCK | host_executor.SOCKET_MODE,
            st_uid=0,
            st_gid=4242,
        )
        with (
            patch.object(host_executor.os, "open", return_value=8),
            patch.object(host_executor.os, "stat", return_value=metadata) as stat_call,
            patch.object(host_executor.os, "close"),
        ):
            host_executor._configure_socket_permissions(
                "/run/yantra/executor.sock", 4242
            )
        self.assertFalse(hasattr(host_executor, "_resolve_desktop_account"))
        self.assertEqual(stat_call.call_args.kwargs["follow_symlinks"], False)

    def test_arbitrary_systemd_target_is_rejected(self) -> None:
        result = host_executor._process_intent({
            "intent": "RESTART_DAEMON",
            "target": "sshd.service",
        })
        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("not an allowed Yantra unit", result["error"])
        command, _ = host_executor._build_command(
            "RESTART_DAEMON", "yantra.service"
        )
        self.assertEqual(command, ["/usr/bin/systemctl", "restart", "yantra.service"])

    def test_targets_are_required_or_forbidden_per_intent(self) -> None:
        required = host_executor._process_intent({
            "intent": "RESTART_DAEMON",
            "target": "",
        })
        removed = host_executor._process_intent({
            "intent": "SYSTEM_UPDATE",
            "target": "",
        })
        self.assertEqual(required["status"], "REJECTED")
        self.assertEqual(removed["status"], "REJECTED")

    def test_snapshot_and_mutation_pipeline_is_single_operation(self) -> None:
        active = 0
        maximum = 0
        state_lock = threading.Lock()

        def execute(intent: str, target: str, started: float):
            nonlocal active, maximum
            with state_lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
            return {"status": "SUCCESS", "intent": intent}

        payload = {"intent": "RESTART_DAEMON", "target": "yantra.service"}
        with patch.object(host_executor, "_execute_locked_intent", side_effect=execute):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(host_executor._process_intent, (payload, payload)))
        self.assertEqual(maximum, 1)

    def test_outputs_are_bounded_before_decoding(self) -> None:
        value = host_executor._bounded_output(b"x" * 10_000, 128)
        self.assertEqual(len(value), 128)

    def test_subprocess_capture_is_bounded_while_pipes_are_drained(self) -> None:
        completed = host_executor._run_bounded_command(
            [sys.executable, "-c", "import sys; print('x'*100000); print('y'*100000, file=sys.stderr)"],
            5,
            128,
            64,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(completed.stdout), 128)
        self.assertEqual(len(completed.stderr), 64)


if __name__ == "__main__":
    unittest.main()
