"""Tests for the host executor snapshot wrapper fallback."""

from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import patch

import core.host_executor as host_executor


class SnapshotFallbackTests(unittest.TestCase):
    def test_missing_wrapper_uses_packaged_module_with_explicit_argv(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"PRE-FLIGHT: PASSED", stderr=b""
        )
        with (
            patch.object(host_executor.Path, "is_file", side_effect=[False, True]),
            patch.object(host_executor, "_run_bounded_command", return_value=completed) as run,
        ):
            ok, message = host_executor._execute_preflight_snapshot()

        self.assertTrue(ok)
        self.assertEqual(message, "PRE-FLIGHT: PASSED")
        run.assert_called_once_with(
            [sys.executable, "-m", "core.cli_snapshot", "--pre-flight"],
            host_executor.SNAPSHOT_TIMEOUT_SECS,
            500,
            500,
        )

    def test_missing_wrapper_and_module_fails_closed(self) -> None:
        with patch.object(host_executor.Path, "is_file", return_value=False):
            ok, message = host_executor._execute_preflight_snapshot()

        self.assertFalse(ok)
        self.assertIn("Mutation blocked", message)


if __name__ == "__main__":
    unittest.main()
