#!/usr/bin/env python3
"""Provision minimal per-service YantraOS credentials without image embedding."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

SOURCE_FILE = Path("/run/archiso/bootmnt/yantra-secrets.env")
KEYVAULT_CONFIG = Path("/etc/yantra/keyvault.json")
OUTPUT_DIR = Path("/etc/yantra")
MAX_SOURCE_BYTES = 64 * 1024
NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")

DAEMON_KEYS = frozenset({
    "YANTRA_CONTROL_TOKEN",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT_NAME",
    "AZURE_DEPLOYMENT_LUNA",
    "AZURE_DEPLOYMENT_TERRA",
    "AZURE_DEPLOYMENT_SOL",
    "YANTRA_TELEMETRY_ENDPOINT",
    "YANTRA_TELEMETRY_TOKEN",
    "YANTRA_NODE_ID",
})
TELEGRAM_KEYS = frozenset({
    "YANTRA_CONTROL_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OPERATOR_CHAT_ID",
})


def _read_bounded(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Unsafe credential source: {path}")
    metadata = path.stat()
    if path == KEYVAULT_CONFIG and (
        metadata.st_uid != 0 or metadata.st_mode & 0o077
    ):
        raise RuntimeError("Key Vault config must be root-owned mode 0600")
    with path.open("rb") as source:
        data = source.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise RuntimeError("Credential source exceeds its size limit")
    return data


def _fetch_keyvault_secret() -> bytes:
    config = json.loads(_read_bounded(KEYVAULT_CONFIG))
    if set(config) != {"vault_url", "secret_name"}:
        raise RuntimeError("Key Vault config must contain only vault_url and secret_name")
    vault_url = str(config["vault_url"]).rstrip("/")
    secret_name = str(config["secret_name"])
    parsed = urllib.parse.urlsplit(vault_url)
    if parsed.scheme != "https" or not parsed.hostname or not NAME.fullmatch(secret_name.upper()):
        raise RuntimeError("Invalid Key Vault configuration")

    token_url = (
        "http://169.254.169.254/metadata/identity/oauth2/token"
        "?api-version=2019-08-01&resource=https%3A%2F%2Fvault.azure.net"
    )
    token_request = urllib.request.Request(token_url, headers={"Metadata": "true"})
    with urllib.request.urlopen(token_request, timeout=5) as response:
        token_payload = json.loads(response.read(MAX_SOURCE_BYTES))
    token = token_payload.get("access_token")
    if not isinstance(token, str) or len(token) < 32:
        raise RuntimeError("Managed identity returned no usable Key Vault token")

    secret_url = (
        f"{vault_url}/secrets/{urllib.parse.quote(secret_name, safe='')}"
        "?api-version=7.4"
    )
    secret_request = urllib.request.Request(
        secret_url, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(secret_request, timeout=10) as response:
        payload = json.loads(response.read(MAX_SOURCE_BYTES))
    value = payload.get("value")
    if not isinstance(value, str):
        raise RuntimeError("Key Vault secret value is missing")
    return value.encode("utf-8")


def parse_environment(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Credential source must be UTF-8") from exc
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or not NAME.fullmatch(name) or name in values:
            raise RuntimeError("Credential source contains an invalid or duplicate key")
        if name not in DAEMON_KEYS | TELEGRAM_KEYS:
            raise RuntimeError(f"Credential key is not allowlisted: {name}")
        if (
            not value
            or not value.isprintable()
            or "\x00" in value
            or any(character.isspace() for character in value)
        ):
            raise RuntimeError(f"Credential value is invalid: {name}")
        values[name] = value

    control = values.get("YANTRA_CONTROL_TOKEN", "")
    if len(control) < 32 or control.startswith("<") or any(c.isspace() for c in control):
        raise RuntimeError("YANTRA_CONTROL_TOKEN must be a non-placeholder 32+ character token")
    return values


def _serialize(values: dict[str, str], allowed: frozenset[str]) -> bytes:
    selected = {name: values[name] for name in sorted(allowed) if name in values}
    return "".join(f"{name}={value}\n" for name, value in selected.items()).encode()


def _atomic_private_write(path: Path, data: bytes) -> None:
    OUTPUT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if OUTPUT_DIR.is_symlink() or OUTPUT_DIR.stat().st_uid != os.geteuid():
        raise RuntimeError("Credential directory must be owned by the provisioner")
    os.chmod(OUTPUT_DIR, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=OUTPUT_DIR)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("Short credential write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        os.chmod(path, 0o600, follow_symlinks=False)
        directory_fd = os.open(OUTPUT_DIR, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Secret provisioning must run as root")
    data = _read_bounded(SOURCE_FILE) if SOURCE_FILE.exists() else _fetch_keyvault_secret()
    values = parse_environment(data)
    _atomic_private_write(OUTPUT_DIR / "daemon.env", _serialize(values, DAEMON_KEYS))
    if TELEGRAM_KEYS <= values.keys():
        _atomic_private_write(
            OUTPUT_DIR / "telegram.env", _serialize(values, TELEGRAM_KEYS)
        )


if __name__ == "__main__":
    main()
