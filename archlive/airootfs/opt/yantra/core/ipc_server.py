"""
YantraOS — Web Dashboard Server (formerly IPC Server)
Target: /opt/yantra/core/ipc_server.py
Milestone 3, Phase 3 Integration

Exposes a FastAPI ASGI application serving the new Web Dashboard
on port 50000. It replaces the legacy UDS socket TUI bridge.

Key invariants:
  • GET / serves core/web/index.html
  • WS /stream serves real-time telemetry and Kriya Loop logs
  • Broadcaster background tasks pump state to all connected clients
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import pathlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

from core.ota_manager import OTAManager, OTAUpdateError

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse

log = logging.getLogger("yantra.ipc_server")

# ── Shared state reference (injected by engine.py at startup) ─────────────────
_state_ref: object | None = None
_active_streaming_queues: set[asyncio.Queue[str]] = set()


def set_state_ref(state: object) -> None:
    """Inject a live KriyaState reference into the web server module."""
    global _state_ref
    _state_ref = state
    log.info("> WEB: State reference registered.")


def push_log_event(message: str) -> None:
    """
    Non-blocking enqueue of a log line for SSE streaming.
    Drops the oldest entry if the queue is full.
    """
    payload = json.dumps({"type": "log", "message": message})
    for q in list(_active_streaming_queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                q.get_nowait()  # Evict oldest
            except asyncio.QueueEmpty:
                pass
            q.put_nowait(payload)


# ── Background Broadcasters ───────────────────────────────────────────────────

async def _broadcast_telemetry() -> None:
    while True:
        try:
            await asyncio.sleep(2.0)
            if _state_ref and _active_streaming_queues:
                vram_used = getattr(_state_ref, "vram_used_gb", 0.0)
                vram_total = getattr(_state_ref, "vram_total_gb", 1.0)
                if vram_total == 0:
                    vram_total = 1.0
                vram_pct = (vram_used / vram_total) * 100.0
                cpu_pct = getattr(_state_ref, "cpu_pct", 0.0)
                
                payload_obj = {
                    "type": "telemetry",
                    "cpu_pct": round(cpu_pct, 1),
                    "vram_pct": round(vram_pct, 1)
                }
                payload_str = json.dumps(payload_obj)
                for q in list(_active_streaming_queues):
                    try:
                        q.put_nowait(payload_str)
                    except asyncio.QueueFull:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning(f"> WEB: Error broadcasting telemetry: {e}")
            await asyncio.sleep(1)


# ── FastAPI App ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Launch and teardown background broadcasters."""
    bg_telemetry = asyncio.create_task(_broadcast_telemetry())
    yield
    bg_telemetry.cancel()


app = FastAPI(
    title="YantraOS Web Dashboard Server",
    description="Internal server for Kriya Loop web dashboard.",
    version="3.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_dashboard():
    """Serve the local web dashboard HTML."""
    index_path = pathlib.Path(__file__).parent / "web" / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"error": "Dashboard not found"}, status_code=404)


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ACTIVE",
        "daemon": "yantra_daemon",
        "timestamp": time.time(),
    })


@app.get("/telemetry")
async def telemetry():
    """Current KriyaState snapshot as JSON."""
    if _state_ref is None:
        return JSONResponse({"error": "State not initialized"}, status_code=503)

    s = _state_ref
    return JSONResponse({
        "daemon_status": "ACTIVE",
        "phase": getattr(s, "phase", "UNKNOWN"),
        "iteration": getattr(s, "iteration", 0),
        "vram_used_gb": round(getattr(s, "vram_used_gb", 0.0), 2),
        "vram_total_gb": round(getattr(s, "vram_total_gb", 0.0), 2),
        "gpu_util_pct": round(getattr(s, "gpu_util_pct", 0.0), 1),
        "cpu_pct": round(getattr(s, "cpu_pct", 0.0), 1),
        "disk_free_gb": round(getattr(s, "disk_free_gb", 0.0), 2),
        "active_model": getattr(s, "active_model", "unknown"),
        "inference_routing": getattr(s, "inference_routing", "LOCAL"),
        "timestamp": time.time(),
    })


@app.post("/command")
async def command(request: Request):
    """Accept a JSON command and dispatch it (e.g. inject thoughts)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    action = body.get("action", "")

    if action == "ping":
        return JSONResponse({"pong": True, "ts": time.time()})

    if action == "get_phase":
        phase = getattr(_state_ref, "phase", "UNKNOWN")
        return JSONResponse({"phase": str(phase)})

    if action == "shutdown":
        if _state_ref is not None:
            _state_ref.shutdown_requested = True  # type: ignore[attr-defined]
            log.info("> WEB: Shutdown requested via /command endpoint.")
        return JSONResponse({"status": "shutdown_requested"})

    if action == "pause":
        if _state_ref is not None:
            _state_ref.is_paused = True  # type: ignore[attr-defined]
            log.info("> WEB: Kriya Loop PAUSED via /command endpoint.")
        return JSONResponse({"status": "paused"})

    if action == "resume":
        if _state_ref is not None:
            _state_ref.is_paused = False  # type: ignore[attr-defined]
            log.info("> WEB: Kriya Loop RESUMED via /command endpoint.")
        return JSONResponse({"status": "resumed"})

    if action == "inject":
        payload = body.get("payload", "")
        if not payload:
            return JSONResponse(
                {"error": "inject requires a non-empty 'payload' field"},
                status_code=400,
            )
        if _state_ref is not None:
            _state_ref.injected_thoughts.append(payload)  # type: ignore[attr-defined]
            log.info(f"> WEB: Injected thought — {payload!r}")
        return JSONResponse({"status": "injected", "payload": payload})

    if action == "set_model":
        route = body.get("route", "")
        model = body.get("model", "")
        if not route or not model:
            return JSONResponse(
                {"error": "set_model requires non-empty 'route' and 'model'"},
                status_code=400,
            )
        if _state_ref is not None:
            _state_ref.active_model      = model        # type: ignore[attr-defined]
            _state_ref.inference_routing = route        # type: ignore[attr-defined]
        return JSONResponse({"status": "model_set", "route": route, "model": model})

    if action == "SYSTEM_OTA_UPDATE":
        try:
            start_time = time.time()
            output = await OTAManager.trigger_system_update()
            execution_time = time.time() - start_time
            return JSONResponse({
                "status": "success",
                "execution_time_seconds": round(execution_time, 2),
                "output": output
            })
        except OTAUpdateError as e:
            execution_time = time.time() - start_time
            return JSONResponse({
                "status": "failed",
                "execution_time_seconds": round(execution_time, 2),
                "output": e.stderr_trace,
                "error": str(e)
            }, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse({"error": f"Unknown action: '{action}'"}, status_code=400)


@app.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """
    SSE endpoint for the local web dashboard and TUI.
    Yields continuous telemetry and log broadcasts.
    """
    async def event_generator():
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=512)
        _active_streaming_queues.add(q)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping to prevent connection drops
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _active_streaming_queues.discard(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Server Bootstrap ──────────────────────────────────────────────────────────

async def serve() -> None:
    """
    Async entry point. Call this from the Kriya Loop engine as a background task.
    Binds to 0.0.0.0:50000 to dynamically serve the Web Dashboard.
    """
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=50000,
        log_level="warning",  # Suppress uvicorn access logs in journal
        access_log=False,
        loop="asyncio",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    log.info("> WEB: Dashboard server starting — binding to 0.0.0.0:50000")
    await server.serve()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    asyncio.run(serve())
