from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import stat
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from core import audit_log
from core import compliance_executor


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _ed25519_pem() -> bytes:
    return ed25519.Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _append_worker(path: str, worker: int, count: int) -> None:
    from core import audit_log as worker_audit

    worker_audit.AUDIT_LOG_PATH = path
    for sequence in range(count):
        worker_audit._append_payload({"worker": worker, "sequence": sequence})


class AuditStateSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.original_path = audit_log.AUDIT_LOG_PATH

    def tearDown(self) -> None:
        audit_log.AUDIT_LOG_PATH = self.original_path
        self.temporary.cleanup()

    def test_creates_private_directory_and_file(self) -> None:
        path = self.root / "audit-state" / "audit.jsonl"
        audit_log.AUDIT_LOG_PATH = str(path)

        audit_log.log_action(phase="PROPOSED", action={"action": "open_url"})

        self.assertEqual(_mode(path.parent), 0o700)
        self.assertEqual(_mode(path), 0o600)
        self.assertFalse((path.parent / ".probe").exists())

    def test_rejects_symlinks_non_regular_files_and_insecure_mode(self) -> None:
        victim = self.root / "victim"
        victim.write_bytes(b"unchanged")
        victim.chmod(0o600)

        audit_log.AUDIT_LOG_PATH = str(self.root / "audit-link")
        os.symlink(victim, audit_log.AUDIT_LOG_PATH)
        with self.assertRaises((OSError, ValueError)):
            audit_log._append_payload({"event": "blocked"})
        self.assertEqual(victim.read_bytes(), b"unchanged")

        os.unlink(audit_log.AUDIT_LOG_PATH)
        os.mkfifo(audit_log.AUDIT_LOG_PATH, 0o600)
        with self.assertRaises((OSError, ValueError)):
            audit_log._append_payload({"event": "blocked"})

        os.unlink(audit_log.AUDIT_LOG_PATH)
        Path(audit_log.AUDIT_LOG_PATH).touch(mode=0o644)
        with self.assertRaises(PermissionError):
            audit_log._append_payload({"event": "blocked"})

    def test_rejects_symlink_parent(self) -> None:
        real_parent = self.root / "real"
        real_parent.mkdir(mode=0o700)
        linked_parent = self.root / "linked"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        audit_log.AUDIT_LOG_PATH = str(linked_parent / "audit.jsonl")

        with self.assertRaises(OSError):
            audit_log._append_payload({"event": "blocked"})

    def test_concurrent_appends_remain_complete(self) -> None:
        path = self.root / "audit.jsonl"
        audit_log.AUDIT_LOG_PATH = str(path)

        with concurrent.futures.ProcessPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(_append_worker, str(path), worker, 40)
                for worker in range(8)
            ]
            for future in futures:
                future.result()

        entries = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(entries), 320)
        self.assertEqual(
            {(entry["worker"], entry["sequence"]) for entry in entries},
            {(worker, sequence) for worker in range(8) for sequence in range(40)},
        )
        previous = "0" * 64
        for entry in entries:
            self.assertEqual(entry["previous_hash"], previous)
            self.assertRegex(entry["entry_hash"], r"^[0-9a-f]{64}$")
            previous = entry["entry_hash"]

    def test_recursive_redaction_and_entry_bounds(self) -> None:
        path = self.root / "audit.jsonl"
        audit_log.AUDIT_LOG_PATH = str(path)
        token = "nested-token-value"
        content = "private file contents"
        action = {
            "action": "file_management",
            "content": content,
            "key": "top-level-key",
            "nested": {
                "Authorization": "Bearer secret",
                "items": [
                    {"api_key": "api-secret"},
                    {"password": "password-secret"},
                    {"accessToken": token},
                ],
            },
            "safe": "visible",
            "large": "x" * 50000,
        }

        audit_log.log_action(
            phase="EXECUTED",
            action=action,
            result="r" * 50000,
            error="e" * 50000,
        )

        encoded = path.read_bytes()
        entry = json.loads(encoded)
        serialized = encoded.decode()
        for secret in (
            content,
            "top-level-key",
            "Bearer secret",
            "api-secret",
            "password-secret",
            token,
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(entry["action_detail"]["safe"], "visible")
        self.assertEqual(
            entry["action_detail"]["content"]["sha256"],
            hashlib.sha256(content.encode()).hexdigest(),
        )
        self.assertTrue(
            entry["action_detail"]["nested"]["items"][2]["accessToken"]["redacted"]
        )
        self.assertLessEqual(len(encoded), audit_log.MAX_AUDIT_ENTRY_BYTES)

    def test_permission_failure_does_not_change_path_or_fallback(self) -> None:
        configured = str(self.root / "denied" / "audit.jsonl")
        audit_log.AUDIT_LOG_PATH = configured
        with mock.patch.object(
            audit_log, "_open_secure_parent", side_effect=PermissionError("denied")
        ):
            with self.assertLogs("yantra.audit_log", level="ERROR"):
                audit_log.log_action(phase="FAILED", action={"action": "test"})

        self.assertEqual(audit_log.AUDIT_LOG_PATH, configured)
        self.assertEqual(
            audit_log.DEFAULT_AUDIT_LOG_PATH, "/var/log/yantra/audit.jsonl"
        )
        self.assertNotIn("/tmp", audit_log.DEFAULT_AUDIT_LOG_PATH)
        self.assertNotIn(".local", audit_log.DEFAULT_AUDIT_LOG_PATH)


class ComplianceStateSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _paths(self) -> tuple[Path, Path]:
        parent = self.root / "compliance-state"
        return parent / "ledger.db", parent / "key.pem"

    def test_creates_private_state_and_reloads_key(self) -> None:
        db_path, key_path = self._paths()
        executor = compliance_executor.ComplianceExecutor(
            db_path=db_path, key_path=key_path
        )
        public_key = executor.private_key.public_key().public_bytes_raw()
        executor.record_consent("CONSENT_GRANTED")

        reloaded = compliance_executor.ComplianceExecutor(
            db_path=db_path, key_path=key_path
        )

        self.assertEqual(_mode(db_path.parent), 0o700)
        self.assertEqual(_mode(db_path), 0o600)
        self.assertEqual(_mode(key_path), 0o600)
        self.assertEqual(
            reloaded.private_key.public_key().public_bytes_raw(), public_key
        )
        self.assertEqual(list(db_path.parent.glob(".yantra-key-*.tmp")), [])

    def test_consent_defaults_denied_and_tracks_latest_state(self) -> None:
        db_path, key_path = self._paths()
        executor = compliance_executor.ComplianceExecutor(
            db_path=db_path, key_path=key_path
        )
        self.assertFalse(executor.consent_granted())
        executor.record_consent("CONSENT_GRANTED")
        self.assertTrue(executor.consent_granted())
        executor.record_consent("CONSENT_REVOKED")
        self.assertFalse(executor.consent_granted())
        with self.assertRaises(ValueError):
            executor.record_consent("UNKNOWN")

    def test_consent_ledger_tampering_is_detected(self) -> None:
        db_path, key_path = self._paths()
        executor = compliance_executor.ComplianceExecutor(
            db_path=db_path, key_path=key_path
        )
        executor.record_consent("CONSENT_GRANTED")
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE consent_ledger SET intent='CONSENT_REVOKED' WHERE id=1"
            )
            connection.commit()
        with self.assertRaises(RuntimeError):
            compliance_executor.ComplianceExecutor(
                db_path=db_path, key_path=key_path
            )

    def test_rejects_key_and_database_symlinks(self) -> None:
        db_path, key_path = self._paths()
        db_path.parent.mkdir(mode=0o700)
        key_target = self.root / "key-target"
        key_target.write_bytes(_ed25519_pem())
        key_target.chmod(0o600)
        key_path.symlink_to(key_target)

        with self.assertRaises((OSError, ValueError)):
            compliance_executor.ComplianceExecutor(
                db_path=db_path, key_path=key_path
            )

        key_path.unlink()
        db_target = self.root / "db-target"
        db_target.touch(mode=0o600)
        db_path.symlink_to(db_target)
        with self.assertRaises((OSError, ValueError)):
            compliance_executor.ComplianceExecutor(
                db_path=db_path, key_path=key_path
            )

    def test_rejects_insecure_modes_owner_and_wrong_key_type(self) -> None:
        db_path, key_path = self._paths()
        db_path.parent.mkdir(mode=0o700)
        key_path.write_bytes(_ed25519_pem())
        key_path.chmod(0o644)
        with self.assertRaises(PermissionError):
            compliance_executor.ComplianceExecutor(
                db_path=db_path, key_path=key_path
            )

        key_path.chmod(0o600)
        db_path.touch(mode=0o644)
        with self.assertRaises(PermissionError):
            compliance_executor.ComplianceExecutor(
                db_path=db_path, key_path=key_path
            )

        foreign = types.SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600,
            st_uid=os.geteuid() + 1,
        )
        with self.assertRaises(PermissionError):
            compliance_executor._validate_private_file(foreign, "Test state")

        db_path.unlink()
        wrong_key = x25519.X25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        key_path.write_bytes(wrong_key)
        key_path.chmod(0o600)
        with self.assertRaises(ValueError):
            compliance_executor.ComplianceExecutor(
                db_path=db_path, key_path=key_path
            )

    def test_environment_paths_and_defaults_have_no_tmp_fallback(self) -> None:
        audit_path = self.root / "configured-audit"
        db_path = self.root / "configured-db"
        key_path = self.root / "configured-key"
        environment = os.environ.copy()
        environment.update(
            {
                "YANTRA_AUDIT_LOG_PATH": str(audit_path),
                "YANTRA_COMPLIANCE_DB_PATH": str(db_path),
                "YANTRA_COMPLIANCE_KEY_PATH": str(key_path),
            }
        )
        code = (
            "import json; from core import audit_log, compliance_executor as c; "
            "print(json.dumps([audit_log.AUDIT_LOG_PATH, c.COMPLIANCE_DB_PATH, "
            "c.COMPLIANCE_KEY_PATH]))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )

        self.assertEqual(
            json.loads(completed.stdout),
            [str(audit_path), str(db_path), str(key_path)],
        )
        self.assertEqual(
            compliance_executor.DEFAULT_COMPLIANCE_DB_PATH,
            "/var/lib/yantra/consent_ledger.db",
        )
        self.assertEqual(
            compliance_executor.DEFAULT_COMPLIANCE_KEY_PATH,
            "/var/lib/yantra/.compliance_key.pem",
        )
        self.assertNotIn("/tmp", compliance_executor.DEFAULT_COMPLIANCE_DB_PATH)
        self.assertNotIn("/tmp", compliance_executor.DEFAULT_COMPLIANCE_KEY_PATH)


if __name__ == "__main__":
    unittest.main()
