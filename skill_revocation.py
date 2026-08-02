# Copyright (c) 2026 Euryale Ferox Private Limited
# SPDX-License-Identifier: MIT

"""Verify and refresh the signed runtime-skill revocation list."""

from __future__ import annotations

import base64
import binascii
import json
import os
import pwd
import re
import secrets
import ssl
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


REVOCATION_URL = "https://yantraos-revocations.vercel.app/.well-known/yantraos/skill-revocations.json"
REVOCATION_PATH = Path("/var/lib/yantra-revocation/current.json")
CANDIDATE_PATH = Path("/run/yantra-revocation/candidate.json")
BOOTSTRAP_PATH = Path(__file__).with_name("skill-revocations.json")
ENVELOPE_SCHEMA = "yantraos/signed-skill-revocations/v1"
PAYLOAD_SCHEMA = "yantraos/skill-revocations/v1"
KEY_ID = "ed25519-3d4259b857a65c27"
PUBLIC_KEY_DER_B64 = "MCowBQYDK2VwAyEA/A8ahg6XGabm2Ed8ZnINiMHaxJVejYLePBo4BMX/AwI="
TRUSTED_PUBLIC_KEYS = {KEY_ID: PUBLIC_KEY_DER_B64}
SIGNATURE_DOMAIN = b"yantraos:skill-revocations:v1\x00"

_UPDATER_USER = "yantra_revocation"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_ENVELOPE_FIELDS = frozenset({"schema", "key_id", "payload", "signature"})
_PAYLOAD_FIELDS = frozenset({"schema", "sequence", "issued_at", "expires_at", "revoked"})
_MAX_DOCUMENT_BYTES = 262_144
_MAX_PAYLOAD_BYTES = 131_072
_MAX_REVOCATIONS = 4_096
_MAX_INTEGER = (2**53) - 1
_CLOCK_SKEW_SECONDS = 300
_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
_DIRECTORY_FLAGS = _READ_FLAGS | os.O_DIRECTORY


@dataclass(frozen=True)
class RevocationList:
    sequence: int
    issued_at: int
    expires_at: int
    revoked: frozenset[tuple[str, str | None]]

    def revokes(self, skill_id: str, version: str) -> bool:
        return (skill_id, None) in self.revoked or (skill_id, version) in self.revoked


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _decode_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {label} JSON") from exc


def _decode_base64(value: Any, label: str, maximum: int) -> bytes:
    if not isinstance(value, str) or len(value) > ((maximum + 2) // 3) * 4:
        raise ValueError(f"Invalid {label}")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Invalid {label}") from exc
    if len(decoded) > maximum:
        raise ValueError(f"Invalid {label}")
    return decoded


def _require_fresh(value: RevocationList, now: int | None) -> None:
    current_time = int(time.time()) if now is None else now
    if value.issued_at > current_time + _CLOCK_SKEW_SECONDS:
        raise ValueError("Revocation list is not valid yet")
    if value.expires_at <= current_time:
        raise ValueError("Revocation list has expired")


def _parse_payload(raw: bytes, *, now: int | None, require_fresh: bool) -> RevocationList:
    payload = _decode_json(raw, "revocation payload")
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise ValueError("Invalid revocation payload fields")

    sequence = payload["sequence"]
    issued_at = payload["issued_at"]
    expires_at = payload["expires_at"]
    if (
        payload["schema"] != PAYLOAD_SCHEMA
        or type(sequence) is not int
        or not 1 <= sequence <= _MAX_INTEGER
        or type(issued_at) is not int
        or not 0 <= issued_at <= _MAX_INTEGER
        or type(expires_at) is not int
        or not issued_at < expires_at <= _MAX_INTEGER
        or not isinstance(payload["revoked"], list)
        or len(payload["revoked"]) > _MAX_REVOCATIONS
    ):
        raise ValueError("Invalid revocation payload values")

    revoked: set[tuple[str, str | None]] = set()
    for entry in payload["revoked"]:
        if not isinstance(entry, dict) or set(entry) not in ({"id"}, {"id", "version"}):
            raise ValueError("Invalid revoked skill entry")
        skill_id = entry["id"]
        version = entry.get("version")
        if (
            not isinstance(skill_id, str)
            or not _IDENTIFIER.fullmatch(skill_id)
            or (version is not None and (not isinstance(version, str) or not _VERSION.fullmatch(version)))
            or (skill_id, version) in revoked
        ):
            raise ValueError("Invalid revoked skill identity")
        revoked.add((skill_id, version))

    result = RevocationList(sequence, issued_at, expires_at, frozenset(revoked))
    if require_fresh:
        _require_fresh(result, now)
    return result


def _public_key(key_id: str) -> ed25519.Ed25519PublicKey:
    encoded_value = TRUSTED_PUBLIC_KEYS.get(key_id)
    if encoded_value is None:
        raise ValueError("Unknown revocation signing key")
    encoded = _decode_base64(encoded_value, "revocation public key", 64)
    key = serialization.load_der_public_key(encoded)
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise ValueError("Revocation trust root is not Ed25519")
    return key


def verify_document(
    raw: bytes,
    *,
    now: int | None = None,
    require_fresh: bool = True,
    public_key: ed25519.Ed25519PublicKey | None = None,
) -> RevocationList:
    """Verify one bounded signed envelope and return its strict payload."""
    if not isinstance(raw, bytes) or len(raw) > _MAX_DOCUMENT_BYTES:
        raise ValueError("Invalid revocation document size")
    envelope = _decode_json(raw, "revocation envelope")
    if not isinstance(envelope, dict) or set(envelope) != _ENVELOPE_FIELDS:
        raise ValueError("Invalid revocation envelope fields")
    key_id = envelope["key_id"]
    if envelope["schema"] != ENVELOPE_SCHEMA or not isinstance(key_id, str):
        raise ValueError("Unknown revocation signing key")

    payload = _decode_base64(envelope["payload"], "revocation payload", _MAX_PAYLOAD_BYTES)
    signature = _decode_base64(envelope["signature"], "revocation signature", 64)
    if len(signature) != 64:
        raise ValueError("Invalid revocation signature")
    try:
        if public_key is not None:
            if key_id != KEY_ID:
                raise ValueError("Unknown revocation signing key")
            key = public_key
        else:
            key = _public_key(key_id)
        key.verify(signature, SIGNATURE_DOMAIN + payload)
    except InvalidSignature as exc:
        raise ValueError("Invalid revocation signature") from exc
    return _parse_payload(payload, now=now, require_fresh=require_fresh)


def _read_regular_file(path: Path, allowed_owners: set[int]) -> bytes:
    descriptor = os.open(path, _READ_FLAGS)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid not in allowed_owners
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or metadata.st_size > _MAX_DOCUMENT_BYTES
        ):
            raise PermissionError(f"Untrusted revocation file: {path}")
        data = bytearray()
        while len(data) <= _MAX_DOCUMENT_BYTES:
            chunk = os.read(descriptor, min(8192, _MAX_DOCUMENT_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > _MAX_DOCUMENT_BYTES:
            raise ValueError("Revocation document is too large")
        return bytes(data)
    finally:
        os.close(descriptor)


def _cache_owners() -> set[int]:
    return {0}


def _updater_uid() -> int:
    try:
        return pwd.getpwnam(_UPDATER_USER).pw_uid
    except KeyError as exc:
        raise PermissionError("Revocation updater account is unavailable") from exc


def _newer(first: RevocationList, second: RevocationList) -> RevocationList:
    if first.sequence == second.sequence:
        if first != second:
            raise ValueError("Revocation sequence collision rejected")
        return first
    older, newer = (first, second) if first.sequence < second.sequence else (second, first)
    if not older.revoked.issubset(newer.revoked):
        raise ValueError("Revoked skill entries cannot be removed")
    return newer


def _bootstrap(*, now: int | None = None, require_fresh: bool = False) -> RevocationList:
    source_owner = os.stat(__file__, follow_symlinks=False).st_uid
    raw = _read_regular_file(BOOTSTRAP_PATH, {source_owner})
    return verify_document(raw, now=now, require_fresh=require_fresh)


def active_revocations(*, now: int | None = None) -> RevocationList:
    """Load current metadata without caching so promotion takes effect immediately."""
    bootstrap = _bootstrap()
    try:
        raw = _read_regular_file(REVOCATION_PATH, _cache_owners())
    except FileNotFoundError:
        _require_fresh(bootstrap, now)
        return bootstrap
    current = _newer(bootstrap, verify_document(raw, require_fresh=False))
    _require_fresh(current, now)
    return current


def ensure_skill_allowed(skill_id: str, version: str) -> None:
    """Fail closed when revocation state is unavailable or matches the skill."""
    try:
        revocations = active_revocations()
    except (OSError, ValueError) as exc:
        raise PermissionError("Skill revocation status is unavailable.") from exc
    if revocations.revokes(skill_id, version):
        raise PermissionError(f"Skill {skill_id!r} version {version!r} is revoked.")


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _fetch_document() -> bytes:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = request.build_opener(request.ProxyHandler({}), request.HTTPSHandler(context=context), _NoRedirect())
    fetch = request.Request(
        REVOCATION_URL,
        headers={"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "YantraOS/2 revocation"},
    )
    with opener.open(fetch, timeout=10) as response:
        if response.status != 200 or response.geturl() != REVOCATION_URL:
            raise ValueError("Unexpected revocation response")
        if response.headers.get_content_type() != "application/json":
            raise ValueError("Unexpected revocation content type")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("Compressed revocation responses are not accepted")
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > _MAX_DOCUMENT_BYTES):
            raise ValueError("Invalid revocation response size")
        raw = response.read(_MAX_DOCUMENT_BYTES + 1)
    if len(raw) > _MAX_DOCUMENT_BYTES:
        raise ValueError("Revocation response is too large")
    return raw


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("Short revocation-file write")
        remaining = remaining[written:]


def _publish_document(raw: bytes, path: Path) -> None:
    parent = path.parent
    if not path.is_absolute() or path.name not in {"candidate.json", "current.json"}:
        raise ValueError("Invalid revocation publication path")
    parent_descriptor = os.open(parent, _DIRECTORY_FLAGS)
    temporary = f".{path.name}-{os.getpid()}-{secrets.token_hex(8)}.tmp"
    temporary_exists = False
    descriptor: int | None = None
    try:
        metadata = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise PermissionError("Untrusted revocation cache directory")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        temporary_exists = True
        _write_all(descriptor, raw)
        os.fchmod(descriptor, 0o644)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        temporary_exists = False
        os.fsync(parent_descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_exists:
            try:
                os.unlink(temporary, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        os.close(parent_descriptor)


def install_document(raw: bytes, *, now: int | None = None) -> tuple[bool, int]:
    """Atomically install newer signed metadata without rollback or un-revocation."""
    candidate = verify_document(raw, now=now)
    bootstrap = _bootstrap()
    cached: RevocationList | None = None
    try:
        current_raw = _read_regular_file(REVOCATION_PATH, {os.geteuid()})
    except FileNotFoundError:
        current = bootstrap
    else:
        cached = verify_document(current_raw, require_fresh=False)
        current = _newer(bootstrap, cached)

    if candidate.sequence < current.sequence:
        raise ValueError("Revocation list rollback rejected")
    if not current.revoked.issubset(candidate.revoked):
        raise ValueError("Revoked skill entries cannot be removed")
    if candidate.sequence == current.sequence and candidate != current:
        raise ValueError("Revocation sequence collision rejected")
    if candidate == cached or (cached is None and candidate == bootstrap):
        return False, candidate.sequence

    _publish_document(raw, REVOCATION_PATH)
    return True, candidate.sequence


def fetch_candidate() -> int:
    raw = _fetch_document()
    sequence = verify_document(raw).sequence
    _publish_document(raw, CANDIDATE_PATH)
    return sequence


def install_candidate() -> tuple[bool, int]:
    if os.geteuid() != 0:
        raise PermissionError("Revocation promotion requires root")
    raw = _read_regular_file(CANDIDATE_PATH, {_updater_uid()})
    return install_document(raw)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in (["fetch"], ["install"]):
        print("usage: skill_revocation.py fetch|install", file=sys.stderr)
        return 2
    try:
        if args == ["fetch"]:
            sequence = fetch_candidate()
            message = "fetched"
        else:
            changed, sequence = install_candidate()
            message = "installed" if changed else "unchanged"
    except Exception as exc:
        print(f"yantra skill revocation update failed: {exc}", file=sys.stderr)
        return 1
    print(f"yantra skill revocation sequence {sequence} {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
