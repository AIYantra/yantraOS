"""
YantraOS — Compliance Executor (Sovereign Data Assertion Layer)
Target: /opt/yantra/core/compliance_executor.py

Localized, read-only compliance socket that streams cryptographically signed
Kriya Loop state assertions to authorized auditors. Designed to satisfy
sovereign data compliance mandates (e.g., India's MeitY DPDP Act §8, §17)
without routing any data through Western hyperscaler telemetry pipelines.

Architecture:
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Kriya Loop (engine.py)                                             │
  │   SENSE ──▶ stream_state_assertion()                               │
  │   REASON ──▶ stream_state_assertion()                              │
  │   ACT ──▶ stream_state_assertion()                                 │
  └───────────┬─────────────────────────────────────────────────────────┘
              │  Non-blocking fire-and-forget
              ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ ComplianceExecutor                                                  │
  │   /run/yantra/compliance.sock (root:yantra 0440, read-only UDS)    │
  │                                                                     │
  │   1. Accept assertion payload (phase, intent, skill SHA-256)       │
  │   2. Canonicalize to deterministic JSON                            │
  │   3. SHA-256 hash (simulated TPM 2.0 PCR extend)                  │
  │   4. Ed25519 sign (simulated TPM attestation key)                  │
  │   5. Stream signed JSON line to all connected auditor clients      │
  └─────────────────────────────────────────────────────────────────────┘

Security invariants:
  • Socket is OUTBOUND ONLY — all incoming bytes from clients are discarded.
  • Socket permissions: root:yantra 0440 (read-only for group).
  • No data leaves the local machine. Zero external network dependencies.
  • The Ed25519 signing key is generated ephemerally at daemon start for
    this Alpha. Production will source from TPM 2.0 NV index / PKCS#11.
  • The PCR hash simulates TPM 2.0 PCR register extension: each assertion
    extends the running hash chain, making any retroactive tampering
    detectable via chain discontinuity.
"""

from __future__ import annotations

import asyncio
import grp
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

log = logging.getLogger("yantra.compliance")

# ── Constants ─────────────────────────────────────────────────────────────────

COMPLIANCE_SOCKET_PATH: str = "/run/yantra/compliance.sock"
COMPLIANCE_SOCKET_MODE: int = 0o440
COMPLIANCE_SOCKET_GROUP: str = "yantra"

# Maximum connected auditor clients. Beyond this, new connections are refused
# to prevent resource exhaustion from rogue processes.
MAX_AUDITOR_CLIENTS: int = 8


# ── Compliance Executor ───────────────────────────────────────────────────────


class ComplianceExecutor:
    """
    Sovereign data compliance assertion layer.

    Binds a read-only UNIX domain socket that streams cryptographically
    signed Kriya Loop state assertions. Auditor processes connect and
    receive a continuous feed of Ed25519-signed JSON lines — each line
    is an immutable, non-repudiable record of the AI agent's state
    transitions and action intents.

    The socket is write-only from the server's perspective. All bytes
    received from connected clients are silently discarded.
    """

    def __init__(self) -> None:
        # ── Ed25519 Signing Key ───────────────────────────────────────
        # Alpha: ephemeral key generated at daemon start.
        # Production: load from TPM 2.0 NV index or PKCS#11 token.
        self._signing_key: Ed25519PrivateKey = Ed25519PrivateKey.generate()
        self._public_key_hex: str = self._signing_key.public_key().public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw,
        ).hex()

        # ── Simulated TPM 2.0 PCR Register ────────────────────────────
        # PCR extend chain: each assertion extends the running hash.
        # PCR[n] = SHA-256(PCR[n-1] || new_measurement)
        # Initial value: all zeros (matches TPM 2.0 PCR reset state).
        self._pcr_state: bytes = b"\x00" * 32

        # ── Connected auditor transports ──────────────────────────────
        self._clients: set[asyncio.StreamWriter] = set()
        self._server: asyncio.AbstractServer | None = None
        self._running: bool = False

        log.info(
            f"> COMPLIANCE: Ed25519 attestation key generated "
            f"(pubkey={self._public_key_hex[:16]}…)"
        )

    # ── PCR Extend (Simulated TPM 2.0) ────────────────────────────────

    def _pcr_extend(self, measurement: bytes) -> str:
        """
        Simulate TPM 2.0 PCR register extension.

        PCR[n] = SHA-256(PCR[n-1] || measurement)

        This creates a hash chain where any retroactive modification
        to a prior assertion breaks the chain — detectable by comparing
        the final PCR value against the expected state.

        Args:
            measurement: The SHA-256 digest of the current assertion payload.

        Returns:
            Hex-encoded PCR value after extension.
        """
        extend_input: bytes = self._pcr_state + measurement
        self._pcr_state = hashlib.sha256(extend_input).digest()
        return self._pcr_state.hex()

    # ── State Assertion Streaming ─────────────────────────────────────

    async def stream_state_assertion(
        self,
        *,
        phase: str,
        iteration: int,
        telemetry: dict[str, Any] | None = None,
        action_intent: list[dict[str, Any]] | None = None,
        active_model: str = "unknown",
        skill_fingerprint: str = "",
    ) -> None:
        """
        Construct, sign, and stream a compliance state assertion.

        This method is called at the end of each critical Kriya Loop
        phase transition (SENSE, REASON, ACT). It is non-blocking and
        fire-and-forget — failures are logged but never propagate to
        the caller.

        Assertion pipeline:
          1. Build canonical JSON payload (deterministic key ordering).
          2. SHA-256 hash the canonical bytes (measurement).
          3. Extend the simulated TPM 2.0 PCR register.
          4. Ed25519 sign the measurement.
          5. Stream the signed assertion to all connected auditor clients.

        Args:
            phase:             Current Kriya phase name (SENSE/REASON/ACT).
            iteration:         Current loop iteration number.
            telemetry:         Hardware telemetry dict from SENSE phase.
            action_intent:     Pending action list from REASON phase.
            active_model:      Current inference model identifier.
            skill_fingerprint: SHA-256 of the active skill/prompt (if any).
        """
        if not self._running:
            return

        try:
            # ── Step 1: Build canonical payload ───────────────────────
            state_payload: dict[str, Any] = {
                "phase": phase,
                "iteration": iteration,
                "active_model": active_model,
                "skill_fingerprint": skill_fingerprint or "none",
                "telemetry": telemetry or {},
                "action_intent": action_intent or [],
            }

            # Deterministic serialization — sorted keys, no whitespace
            canonical: bytes = json.dumps(
                state_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")

            # ── Step 2: SHA-256 measurement ───────────────────────────
            measurement: bytes = hashlib.sha256(canonical).digest()
            measurement_hex: str = measurement.hex()

            # ── Step 3: PCR extend ────────────────────────────────────
            pcr_hex: str = self._pcr_extend(measurement)

            # ── Step 4: Ed25519 signature ─────────────────────────────
            signature: bytes = self._signing_key.sign(measurement)
            signature_hex: str = signature.hex()

            # ── Step 5: Construct signed assertion line ───────────────
            assertion: dict[str, Any] = {
                "timestamp": time.time(),
                "state": state_payload,
                "pcr_hash": pcr_hex,
                "measurement": measurement_hex,
                "signature": signature_hex,
                "pubkey": self._public_key_hex,
            }

            line: bytes = json.dumps(assertion, separators=(",", ":")).encode("utf-8") + b"\n"

            # ── Stream to all connected auditor clients ───────────────
            dead_clients: set[asyncio.StreamWriter] = set()
            for writer in self._clients:
                try:
                    writer.write(line)
                    await writer.drain()
                except (ConnectionResetError, BrokenPipeError, OSError):
                    dead_clients.add(writer)

            # Prune dead connections
            for writer in dead_clients:
                self._clients.discard(writer)
                try:
                    writer.close()
                except Exception:
                    pass

            log.debug(
                f"> COMPLIANCE: Assertion streamed — "
                f"phase={phase} iter={iteration} "
                f"clients={len(self._clients)} "
                f"pcr={pcr_hex[:16]}…"
            )

        except Exception as exc:
            # Compliance failures are NEVER fatal to the Kriya Loop.
            # Log and continue — the engine must not stall on audit I/O.
            log.warning(
                f"> COMPLIANCE: Assertion failed (non-fatal): "
                f"{type(exc).__name__}: {exc}"
            )

    # ── Socket Server ─────────────────────────────────────────────────

    async def _handle_auditor(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """
        Handle a new auditor connection.

        The compliance socket is OUTBOUND ONLY:
          • The client is registered to receive assertion streams.
          • All incoming bytes from the client are silently discarded.
          • The connection persists until the client disconnects.
        """
        if len(self._clients) >= MAX_AUDITOR_CLIENTS:
            log.warning(
                f"> COMPLIANCE: Auditor connection refused — "
                f"max clients reached ({MAX_AUDITOR_CLIENTS})"
            )
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            return

        self._clients.add(writer)
        client_count: int = len(self._clients)
        log.info(f"> COMPLIANCE: Auditor connected (total={client_count})")

        # Send the public key announcement as the first line so the
        # auditor can verify all subsequent signatures.
        announcement: dict[str, Any] = {
            "type": "compliance_handshake",
            "version": "yantraos/compliance/v1alpha",
            "pubkey": self._public_key_hex,
            "pcr_initial": ("00" * 32),
            "timestamp": time.time(),
        }
        try:
            writer.write(
                json.dumps(announcement, separators=(",", ":")).encode("utf-8") + b"\n"
            )
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            self._clients.discard(writer)
            return

        # ── Read loop: discard all incoming bytes ─────────────────────
        # The socket is read-only from the client's perspective.
        # We must still read to detect disconnection (EOF).
        try:
            while True:
                data: bytes = await reader.read(4096)
                if not data:
                    break  # Client disconnected (EOF)
                # Silently discard — this is an outbound-only socket.
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            log.info(
                f"> COMPLIANCE: Auditor disconnected "
                f"(remaining={len(self._clients)})"
            )

    async def start(self) -> None:
        """
        Bind the compliance socket and begin accepting auditor connections.

        Socket lifecycle:
          1. Remove stale socket file if present.
          2. Bind asyncio UNIX server to COMPLIANCE_SOCKET_PATH.
          3. Set permissions to 0440, ownership to root:yantra.
          4. Begin accepting connections.
        """
        socket_path: Path = Path(COMPLIANCE_SOCKET_PATH)

        # Clean up stale socket
        if socket_path.exists():
            log.info(f"> COMPLIANCE: Removing stale socket {COMPLIANCE_SOCKET_PATH}")
            socket_path.unlink()

        # Ensure parent directory exists
        socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Start server
        self._server = await asyncio.start_unix_server(
            self._handle_auditor,
            path=COMPLIANCE_SOCKET_PATH,
        )

        # Set socket permissions: root:yantra 0440 (read-only for group)
        os.chmod(COMPLIANCE_SOCKET_PATH, COMPLIANCE_SOCKET_MODE)
        try:
            yantra_gid: int = grp.getgrnam(COMPLIANCE_SOCKET_GROUP).gr_gid
            os.chown(COMPLIANCE_SOCKET_PATH, 0, yantra_gid)
            log.info(
                f"> COMPLIANCE: Socket permissions set — "
                f"{COMPLIANCE_SOCKET_PATH} root:{COMPLIANCE_SOCKET_GROUP} "
                f"{oct(COMPLIANCE_SOCKET_MODE)}"
            )
        except KeyError:
            log.warning(
                f"> COMPLIANCE: Group '{COMPLIANCE_SOCKET_GROUP}' not found. "
                f"Socket accessible only to root."
            )
        except PermissionError:
            # Non-root daemon — permissions set to mode only.
            log.warning(
                "> COMPLIANCE: Cannot chown socket (not root). "
                "Mode-only permissions applied."
            )

        self._running = True
        log.info(
            f"> COMPLIANCE: Sovereign assertion socket active — "
            f"{COMPLIANCE_SOCKET_PATH}"
        )
        log.info(
            f"> COMPLIANCE: Attestation pubkey — "
            f"{self._public_key_hex}"
        )

    async def shutdown(self) -> None:
        """
        Gracefully shut down the compliance socket.

        Closes all auditor connections and removes the socket file.
        """
        self._running = False

        # Close all client connections
        for writer in list(self._clients):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()

        # Stop the server
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Remove socket file
        socket_path: Path = Path(COMPLIANCE_SOCKET_PATH)
        if socket_path.exists():
            try:
                socket_path.unlink()
            except OSError:
                pass

        log.info("> COMPLIANCE: Socket shut down. All auditor connections closed.")

    @property
    def is_active(self) -> bool:
        """Whether the compliance socket is bound and accepting connections."""
        return self._running and self._server is not None

    @property
    def client_count(self) -> int:
        """Number of currently connected auditor clients."""
        return len(self._clients)

    @property
    def pcr_state_hex(self) -> str:
        """Current PCR register value (hex-encoded)."""
        return self._pcr_state.hex()

    @property
    def public_key_hex(self) -> str:
        """Ed25519 public key for assertion verification (hex-encoded)."""
        return self._public_key_hex


# ── Module-level singleton ────────────────────────────────────────────────────
# The engine imports and initializes this instance. Only one compliance
# executor exists per daemon lifecycle.

compliance_executor: ComplianceExecutor = ComplianceExecutor()
