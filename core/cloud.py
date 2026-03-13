"""
YantraOS — Cloud Bridge
Local-to-Cloud async client connecting the Kriya Loop daemon
to the deployed www.yantraos.com Web HUD.

Provides two capabilities:
  1. fetch_skill_from_cloud(query) — RAG skill lookup against Pinecone
  2. emit_telemetry(payload) — push daemon telemetry to the Web HUD
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

try:
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False

log = logging.getLogger("yantra.cloud")

# ── Config ────────────────────────────────────────────────────────

HUD_BASE_URL = os.environ.get("YANTRA_HUD_URL", "https://www.yantraos.com")
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15) if _AIOHTTP_AVAILABLE else None
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5  # seconds


# ── Types ─────────────────────────────────────────────────────────

SkillResult = dict[str, Any]
TelemetryPayload = dict[str, Any]


# ── Helpers ───────────────────────────────────────────────────────

async def _get(session: "aiohttp.ClientSession", url: str, **params) -> dict:
    """Perform a GET with retry-backoff logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url, params=params, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            wait = RETRY_BACKOFF ** attempt
            log.warning(f"GET {url} failed (attempt {attempt}): {e}. Retrying in {wait}s...")
            await asyncio.sleep(wait)
    return {}


async def _post(session: "aiohttp.ClientSession", url: str, payload: dict) -> dict:
    """Perform a POST with retry-backoff logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.post(url, json=payload, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            wait = RETRY_BACKOFF ** attempt
            log.warning(f"POST {url} failed (attempt {attempt}): {e}. Retrying in {wait}s...")
            await asyncio.sleep(wait)
    return {}


# ── Public API ────────────────────────────────────────────────────

async def fetch_skill_from_cloud(query: str) -> list[SkillResult]:
    """
    Query www.yantraos.com/api/skills/search for relevant capabilities.

    Used by the Kriya Loop PATCH phase to resolve unknown dependencies —
    the daemon asks the cloud RAG store what skill can fulfill the need.

    Args:
        query: Natural language description of the needed capability.

    Returns:
        A list of SkillResult dicts matching the yantraos/skill/v1 schema,
        sorted by cosine similarity score (highest first).
        Returns [] on any network failure (fail-safe: daemon continues locally).
    """
    if not _AIOHTTP_AVAILABLE:
        log.error("> ERROR: aiohttp not installed. Run: pip install aiohttp")
        return []

    url = f"{HUD_BASE_URL}/api/skills/search"
    log.info(f"> CLOUD: Fetching skill for query: '{query[:60]}...'")

    try:
        async with aiohttp.ClientSession() as session:
            data = await _get(session, url, query=query)
            results: list[SkillResult] = data.get("results", [])
            log.info(f"> CLOUD: Received {len(results)} skill match(es).")
            return results
    except Exception as e:
        log.error(f"> ERROR: Cloud skill fetch failed: {e}")
        return []  # Fail-safe: return empty, daemon resolves locally


async def emit_telemetry(payload: TelemetryPayload) -> bool:
    """
    Push daemon telemetry to www.yantraos.com/api/telemetry/ingest/.

    Used by the Kriya Loop UPDATE_ARCHITECTURE phase to stream
    real-time hardware metrics and Kriya state to the Web HUD.

    Args:
        payload: Dict containing telemetry data. Expected schema:
            {
                "daemon_status": str,   # "ACTIVE" | "BOOTING" | "ERROR"
                "vram_used_gb": float,
                "vram_total_gb": float,
                "gpu_util_pct": float,
                "active_model": str,
                "inference_routing": str,  # "LOCAL" | "CLOUD"
                "kriya_phase": str,        # "SENSE" | "REASON" | "ACT" | "REMEMBER"
                "timestamp": float,        # Unix epoch
            }

    Returns:
        True if the telemetry was accepted, False on any failure.
        Failures are logged but never raise — telemetry is best-effort.
    """
    if not _AIOHTTP_AVAILABLE:
        log.error("> ERROR: aiohttp not installed. Run: pip install aiohttp")
        return False

    # TRACER BULLET: Hardcoded URL — no interpolation, no trailing slash
    url = "https://www.yantraos.com/api/telemetry/ingest/"

    # Stamp the payload if not already timestamped
    if "timestamp" not in payload:
        payload["timestamp"] = time.time()

    # TRACER BULLET: Fix VRAM percentage type mismatch
    # Ensure it's a pure number! Strip '%' and rename 'util_pct' exactly as Vercel expects.
    if "vram_usage" in payload:
        v_u = payload["vram_usage"]
        pct = v_u.get("percent", v_u.get("util_pct", 0))
        if isinstance(pct, str):
            pct = pct.replace('%', '')
            
        payload["vram_usage"] = {
            "used_gb": round(float(v_u.get("used_gb", 0)), 2),
            "total_gb": round(float(v_u.get("total_gb", 0)), 2),
            "percent": round(float(pct), 1)
        }

    log.debug(f"> TELEMETRY: Emitting {payload.get('kriya_phase', 'UNKNOWN')} state to cloud.")

    # TRACER BULLET: Auth stripped — Content-Type only, no Bearer token
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('YANTRA_TELEMETRY_TOKEN')}"
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            await _post(session, url, payload)
            return True
    except Exception as e:
        log.warning(f"> TELEMETRY: Emission failed (non-critical): {e}")
        return False  # Never block the daemon on telemetry failure


# ── Convenience Sync Wrapper ──────────────────────────────────────

def fetch_skill_sync(query: str) -> list[SkillResult]:
    """Synchronous wrapper for use in non-async contexts."""
    return asyncio.run(fetch_skill_from_cloud(query))


def emit_telemetry_sync(payload: TelemetryPayload) -> bool:
    """Synchronous wrapper for use in non-async contexts."""
    return asyncio.run(emit_telemetry(payload))
