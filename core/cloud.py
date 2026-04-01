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
                if resp.status == 422:
                    log.warning(f"POST {url} failed with 422 Unprocessable Entity. Dropping payload.")
                    return {}
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
    Push daemon telemetry to the Web HUD ingress API.
    Used by the Kriya Loop to stream real-time hardware metrics.
    """
    if not _AIOHTTP_AVAILABLE:
        log.error("> ERROR: aiohttp not installed. Run: pip install aiohttp")
        return False

    url = os.environ.get("YANTRA_TELEMETRY_URL", "http://127.0.0.1:3000/api/telemetry/heartbeat")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('YANTRA_DAEMON_KEY', 'dev-local-daemon-key')}"
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
