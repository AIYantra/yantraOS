from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import provision_runtime_secrets as provision


VALID = b"""YANTRA_CONTROL_TOKEN=0123456789abcdef0123456789abcdef
AZURE_OPENAI_ENDPOINT=https://example.openai.azure.com
AZURE_OPENAI_API_KEY=azure-key
AZURE_OPENAI_DEPLOYMENT_NAME=model
YANTRA_NODE_ID=node-01
YANTRA_TELEMETRY_ENDPOINT=https://example.test/api/telemetry/heartbeat
YANTRA_TELEMETRY_TOKEN=node-token
TELEGRAM_BOT_TOKEN=bot-token
TELEGRAM_OPERATOR_CHAT_ID=42
"""


class SecretProvisioningTests(unittest.TestCase):
    def test_parser_requires_strong_control_token_and_allowlisted_unique_keys(self):
        values = provision.parse_environment(VALID)
        self.assertEqual(values["YANTRA_NODE_ID"], "node-01")
        for invalid in (
            b"YANTRA_CONTROL_TOKEN=short\n",
            VALID + b"UNEXPECTED_SECRET=value\n",
            VALID + b"YANTRA_NODE_ID=duplicate\n",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                provision.parse_environment(invalid)

    def test_per_service_files_are_private_and_minimal(self):
        values = provision.parse_environment(VALID)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary, "yantra")
            with patch.object(provision, "OUTPUT_DIR", root):
                provision._atomic_private_write(
                    root / "daemon.env",
                    provision._serialize(values, provision.DAEMON_KEYS),
                )
                provision._atomic_private_write(
                    root / "telegram.env",
                    provision._serialize(values, provision.TELEGRAM_KEYS),
                )

            daemon = (root / "daemon.env").read_text()
            telegram = (root / "telegram.env").read_text()
            self.assertIn("AZURE_OPENAI_API_KEY", daemon)
            self.assertNotIn("TELEGRAM_BOT_TOKEN", daemon)
            self.assertIn("TELEGRAM_BOT_TOKEN", telegram)
            self.assertNotIn("AZURE_OPENAI_API_KEY", telegram)
            self.assertEqual((root / "daemon.env").stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / "telegram.env").stat().st_mode & 0o777, 0o600)

    def test_keyvault_config_requires_root_private_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary, "keyvault.json")
            path.write_text('{"vault_url":"https://vault.example","secret_name":"yantra"}')
            path.chmod(0o644)
            with patch.object(provision, "KEYVAULT_CONFIG", path), self.assertRaises(RuntimeError):
                provision._read_bounded(path)

    def test_azure_secret_names_allow_hyphens_and_full_length(self):
        self.assertTrue(provision.AZURE_SECRET_NAME.fullmatch("yantra-runtime-env"))
        self.assertTrue(provision.AZURE_SECRET_NAME.fullmatch("a"))
        self.assertTrue(provision.AZURE_SECRET_NAME.fullmatch("a" * 127))
        self.assertFalse(provision.AZURE_SECRET_NAME.fullmatch("a" * 128))
        self.assertFalse(provision.AZURE_SECRET_NAME.fullmatch("bad_name"))


if __name__ == "__main__":
    unittest.main()
