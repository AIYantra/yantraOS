"""
YantraOS — Cloud Telemetry Emitter
Target: /opt/yantra/core/cloud.py

Streams hardware telemetry and Kriya loop state to the Web HUD fleet dashboard.
Designed to be fired asynchronously from the engine's main loop without blocking.
"""

import asyncio
import json
import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import KriyaState

log = logging.getLogger("yantra.cloud")

# The endpoint on the central web HUD
TELEMETRY_ENDPOINT = os.getenv("YANTRA_TELEMETRY_ENDPOINT", "http://localhost:3000/api/telemetry/heartbeat")

async def stream_telemetry(state: "KriyaState") -> None:
    """
    Constructs and emits a telemetry payload to the Web HUD.
    Fails silently on timeout or network error to prevent stalling the daemon.
    """
    daemon_key = os.getenv("YANTRA_TELEMETRY_TOKEN")
    if not daemon_key:
        log.debug("> CLOUD: Skipping telemetry emission — YANTRA_TELEMETRY_TOKEN not set.")
        return

    # Determine node_id (fallback to hostname if not explicitly configured)
    node_id = os.getenv("YANTRA_NODE_ID")
    if not node_id:
        import socket
        node_id = socket.gethostname()

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
        "node_id": node_id,
        "daemon_status": daemon_status,
        "active_model": state.active_model,
        "vram_percent": round(vram_percent, 1),
        "cpu_load": round(state.cpu_pct, 1),
        "ram_percent": round(state.ram_percent, 1),
        "current_phase": state.phase.value if state.phase else "IDLE",
        "ota_version": os.getenv("YANTRA_OTA_VERSION", "v1.0.0"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "daemon_key": daemon_key
    }

    # Extract the tail of the thought stream as per the directive
    if state.thought_stream:
        payload["thought_stream_tail"] = state.thought_stream[-1]
    
    try:
        import aiohttp
    except ImportError:
        log.warning("> CLOUD: aiohttp not installed. Cannot stream telemetry.")
        return

    try:
        timeout = aiohttp.ClientTimeout(total=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(TELEMETRY_ENDPOINT, json=payload) as response:
                if response.status not in (200, 201):
                    err_text = await response.text()
                    log.warning(f"> CLOUD: DEGRADED_CLOUD — Telemetry rejected ({response.status}): {err_text}")
                    state.thought_stream.append(f"[{time.strftime('%H:%M:%S')}] DEGRADED_CLOUD: Telemetry rejected ({response.status})")
                else:
                    log.debug("> CLOUD: Telemetry payload delivered successfully.")
    except asyncio.TimeoutError:
        log.warning("> CLOUD: DEGRADED_CLOUD — Telemetry dispatch timed out (10s).")
        state.thought_stream.append(f"[{time.strftime('%H:%M:%S')}] DEGRADED_CLOUD: Telemetry dispatch timed out")
    except Exception as e:
        log.warning(f"> CLOUD: DEGRADED_CLOUD — Network error emitting telemetry: {e}")
        state.thought_stream.append(f"[{time.strftime('%H:%M:%S')}] DEGRADED_CLOUD: Network error {type(e).__name__}")
