"""
YantraOS — Cloud Telemetry Emitter
Target: /opt/yantra/core/cloud.py

Streams hardware telemetry and Kriya loop state to the Web HUD fleet dashboard.
Designed to be fired asynchronously from the engine's main loop without blocking.
"""

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from .engine import KriyaState

log = logging.getLogger("yantra.cloud")

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
MAX_ENDPOINT_LENGTH = 2048
MAX_REJECTION_BODY_BYTES = 1024


def _validate_telemetry_endpoint(endpoint: str) -> str:
    if (
        not endpoint
        or len(endpoint) > MAX_ENDPOINT_LENGTH
        or endpoint != endpoint.strip()
        or not endpoint.isprintable()
        or any(char.isspace() for char in endpoint)
    ):
        raise ValueError("Invalid YANTRA_TELEMETRY_ENDPOINT")

    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid YANTRA_TELEMETRY_ENDPOINT") from exc

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower() if parsed.hostname else None
    if scheme not in {"https", "http"}:
        raise ValueError("YANTRA_TELEMETRY_ENDPOINT scheme is not allowed")
    if not hostname or not parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise ValueError("YANTRA_TELEMETRY_ENDPOINT must not contain credentials")
    if port is not None and not 0 < port <= 65535:
        raise ValueError("YANTRA_TELEMETRY_ENDPOINT has an invalid port")
    if parsed.fragment:
        raise ValueError("YANTRA_TELEMETRY_ENDPOINT must not contain a fragment")
    if scheme == "http" and hostname not in _LOOPBACK_HOSTS:
        raise ValueError("HTTP telemetry is restricted to exact loopback hosts")
    return endpoint


# Validate configuration when the daemon imports this module and again before use.
TELEMETRY_ENDPOINT = _validate_telemetry_endpoint(
    os.getenv(
        "YANTRA_TELEMETRY_ENDPOINT",
        "http://localhost:3000/api/telemetry/heartbeat",
    )
)

async def stream_telemetry(state: "KriyaState") -> None:
    """
    Constructs and emits a telemetry payload to the Web HUD.
    Fails silently on timeout or network error to prevent stalling the daemon.
    """
    try:
        endpoint = _validate_telemetry_endpoint(TELEMETRY_ENDPOINT)
    except ValueError:
        log.error("> CLOUD: Refusing invalid YANTRA_TELEMETRY_ENDPOINT.")
        return

    telemetry_token = os.getenv("YANTRA_TELEMETRY_TOKEN")
    if not telemetry_token:
        log.debug("> CLOUD: Skipping telemetry emission — YANTRA_TELEMETRY_TOKEN not set.")
        return
    if not telemetry_token.isprintable() or any(char.isspace() for char in telemetry_token):
        log.error("> CLOUD: Refusing invalid YANTRA_TELEMETRY_TOKEN header value.")
        return

    node_id = os.getenv("YANTRA_NODE_ID")
    if not node_id:
        log.error("> CLOUD: YANTRA_NODE_ID is required for node-bound telemetry.")
        return

    # Determine daemon status mapping
    if state.shutdown_requested:
        daemon_status = "OFFLINE"
    elif state.phase:
        daemon_status = "ACTIVE"
    else:
        daemon_status = "BOOTING"

    vram_percent = 0.0
    if state.vram_total_gb > 0:
        vram_percent = (state.vram_used_gb / state.vram_total_gb) * 100.0

    # Build the payload matching HeartbeatPayloadSchema in Web HUD route.ts
    payload = {
        "node_id": str(node_id)[:128],
        "daemon_status": daemon_status,
        "active_model": str(state.active_model)[:128],
        "vram_percent": round(vram_percent, 1),
        "cpu_load": round(state.cpu_pct, 1),
        "ram_percent": round(state.ram_percent, 1),
        "current_phase": str(state.phase.value)[:64] if state.phase else "IDLE",
        "ota_version": os.getenv("YANTRA_OTA_VERSION", "v1.0.0")[:64],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    try:
        import aiohttp
    except ImportError:
        log.warning("> CLOUD: aiohttp not installed. Cannot stream telemetry.")
        return

    try:
        timeout = aiohttp.ClientTimeout(total=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {telemetry_token}"},
                allow_redirects=False,
            ) as response:
                if response.status not in (200, 201):
                    await response.content.read(MAX_REJECTION_BODY_BYTES)
                    log.warning(f"> CLOUD: DEGRADED_CLOUD — Telemetry rejected ({response.status})")
                    state.thought_stream.append(f"[{time.strftime('%H:%M:%S')}] DEGRADED_CLOUD: Telemetry rejected ({response.status})")
                else:
                    log.debug("> CLOUD: Telemetry payload delivered successfully.")
    except asyncio.TimeoutError:
        log.warning("> CLOUD: DEGRADED_CLOUD — Telemetry dispatch timed out (10s).")
        state.thought_stream.append(f"[{time.strftime('%H:%M:%S')}] DEGRADED_CLOUD: Telemetry dispatch timed out")
    except Exception as exc:
        log.warning("> CLOUD: DEGRADED_CLOUD — Network error emitting telemetry (%s)", type(exc).__name__)
        state.thought_stream.append(f"[{time.strftime('%H:%M:%S')}] DEGRADED_CLOUD: Telemetry unavailable")


async def revoke_telemetry() -> bool:
    """Request deletion of this authenticated node's remote telemetry row."""
    try:
        endpoint = _validate_telemetry_endpoint(TELEMETRY_ENDPOINT)
    except ValueError:
        return False
    token = os.getenv("YANTRA_TELEMETRY_TOKEN")
    node_id = os.getenv("YANTRA_NODE_ID")
    if not token or not node_id or not token.isprintable() or any(c.isspace() for c in token):
        return False
    try:
        import aiohttp

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10.0)) as session:
            async with session.delete(
                endpoint,
                headers={"Authorization": f"Bearer {token}"},
                allow_redirects=False,
            ) as response:
                await response.content.read(MAX_REJECTION_BODY_BYTES)
                return response.status in (200, 204)
    except Exception as exc:
        log.warning("> CLOUD: Remote telemetry revocation failed (%s)", type(exc).__name__)
        return False
