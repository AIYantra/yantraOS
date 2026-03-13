"""
YantraOS — UNIX Domain Socket IPC Server
Target: /opt/yantra/core/ipc_server.py
Milestone 2, Task 2.1

Exposes a FastAPI ASGI application bound exclusively to a UDS node at
/run/yantra/ipc.sock. The socket is created and chmod'd to 0o660
immediately after uvicorn initialization to enforce the yantra_daemon:yantra
ownership boundary established in Milestone 1 (tmpfiles.d).

Consumers of this server (e.g., the Yantra Shell TUI via bridge.py) connect
via the UDS path — no TCP port is exposed, eliminating the entire remote
network attack surface for IPC.

Key invariants:
  • Stale socket cleanup before bind (idempotent restarts)
  • chmod 0o660 after bind (restricts to yantra group)
  • All endpoints return structured JSON for TUI consumption
  • /stream endpoint is a Server-Sent Events stream for ThoughtStream widget
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

log = logging.getLogger("yantra.ipc_server")

# ── Constants ─────────────────────────────────────────────────────────────────

UDS_PATH: str = "/run/yantra/ipc.sock"
# 0o660: yantra_daemon rw, yantra group rw, world none.
# Matches the 0770 directory mask from tmpfiles.d — the socket itself is
# tighter because only group-level readability is required for the TUI.
UDS_CHMOD: int = 0o660

# ── Shared state reference (injected by engine.py at startup) ─────────────────
# The engine calls `set_state_ref(state)` after constructing KriyaState so
# that the IPC server can serve live telemetry without copying or locking.
_state_ref: object | None = None
_log_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=512)


def set_state_ref(state: object) -> None:
    """Inject a live KriyaState reference into the IPC server module."""
    global _state_ref
    _state_ref = state
    log.info("> IPC: State reference registered.")


def push_log_event(message: str) -> None:
    """
    Non-blocking enqueue of a log line for SSE streaming.
    Drops the oldest entry if the queue is full to avoid back-pressure
    on the daemon's main loop.
    """
    try:
        _log_queue.put_nowait(message)
    except asyncio.QueueFull:
        try:
            _log_queue.get_nowait()  # Evict oldest
        except asyncio.QueueEmpty:
            pass
        _log_queue.put_nowait(message)


# ── FastAPI App ───────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Apply socket permissions immediately after uvicorn creates the file."""
    # At this point uvicorn has already created the socket file.
    if os.path.exists(UDS_PATH):
        os.chmod(UDS_PATH, UDS_CHMOD)
        log.info(
            f"> IPC: Socket permissions set — {UDS_PATH} "
            f"[{oct(UDS_CHMOD)}] (yantra_daemon:yantra rw)"
        )
    yield
    # Cleanup on shutdown
    if os.path.exists(UDS_PATH):
        try:
            os.unlink(UDS_PATH)
            log.info(f"> IPC: Socket removed on graceful shutdown: {UDS_PATH}")
        except OSError as exc:
            log.warning(f"> IPC: Could not remove socket on shutdown: {exc}")


app = FastAPI(
    title="YantraOS IPC Server",
    description="Internal UNIX Domain Socket API for Kriya Loop ↔ TUI communication.",
    version="2.0.0",
    docs_url=None,   # Disable Swagger — not a public API
    redoc_url=None,
    lifespan=lifespan,
)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness check. Returns daemon status and uptime."""
    return JSONResponse({
        "status": "ACTIVE",
        "daemon": "yantra_daemon",
        "socket": UDS_PATH,
        "timestamp": time.time(),
    })


@app.get("/telemetry")
async def telemetry() -> JSONResponse:
    """
    Return the current KriyaState snapshot as structured JSON.
    The TUI polls this endpoint every 2 seconds for the GPUHealth widget.
    """
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
        "log_tail": list(getattr(s, "log_tail", []))[-30:],
        "timestamp": time.time(),
    })


@app.post("/command")
async def command(request: Request) -> JSONResponse:
    """
    Accept a JSON command from the TUI and dispatch it.

    Supported actions:
      • {"action": "shutdown"}    — request graceful daemon shutdown
      • {"action": "ping"}        — roundtrip latency check
      • {"action": "get_phase"}   — return current Kriya phase name
      • {"action": "pause"}       — pause the Kriya Loop
      • {"action": "resume"}      — resume the Kriya Loop
      • {"action": "inject", "payload": "..."}  — inject a thought/command
    """
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
            log.info("> IPC: Shutdown requested via /command endpoint.")
        return JSONResponse({"status": "shutdown_requested"})

    if action == "pause":
        if _state_ref is not None:
            _state_ref.is_paused = True  # type: ignore[attr-defined]
            log.info("> IPC: Kriya Loop PAUSED via /command endpoint.")
        return JSONResponse({"status": "paused"})

    if action == "resume":
        if _state_ref is not None:
            _state_ref.is_paused = False  # type: ignore[attr-defined]
            log.info("> IPC: Kriya Loop RESUMED via /command endpoint.")
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
            log.info(f"> IPC: Injected thought — {payload!r}")
        return JSONResponse({"status": "injected", "payload": payload})

    if action == "set_model":
        route = body.get("route", "")
        model = body.get("model", "")
        if not route or not model:
            return JSONResponse(
                {"error": "set_model requires non-empty 'route' and 'model' fields"},
                status_code=400,
            )
        if _state_ref is not None:
            _state_ref.active_model      = model        # type: ignore[attr-defined]
            _state_ref.inference_routing = route        # type: ignore[attr-defined]
            log.info(f"> IPC: Model changed — route={route!r}, model={model!r}")
        return JSONResponse({"status": "model_set", "route": route, "model": model})

    return JSONResponse({"error": f"Unknown action: '{action}'"}, status_code=400)


@app.get("/stream")
async def stream() -> StreamingResponse:
    """
    Server-Sent Events endpoint for the TUI ThoughtStream widget.
    Streams log lines from the shared queue as they are produced by the
    Kriya Loop, with a 15s keepalive ping to prevent proxy timeouts.
    """
    async def event_generator() -> AsyncIterator[str]:
        keepalive_interval = 15.0
        last_ping = time.monotonic()

        while True:
            try:
                # Wait up to 1s for a new log event
                message = await asyncio.wait_for(
                    _log_queue.get(), timeout=1.0
                )
                yield f"data: {json.dumps({'log': message})}\n\n"
            except asyncio.TimeoutError:
                pass

            # Emit keepalive comment to prevent SSE connection drop
            if time.monotonic() - last_ping >= keepalive_interval:
                yield ": keepalive\n\n"
                last_ping = time.monotonic()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Server Bootstrap ──────────────────────────────────────────────────────────


def _cleanup_stale_socket(uds_path: str) -> None:
    """
    Remove a stale socket file if it exists.

    A stale socket is left behind when the daemon is killed (SIGKILL) rather
    than stopped gracefully. Without this cleanup, uvicorn raises
    [Errno 98] Address already in use on the next start.
    """
    if os.path.exists(uds_path):
        try:
            file_stat = os.stat(uds_path)
            if stat.S_ISSOCK(file_stat.st_mode):
                os.unlink(uds_path)
                log.warning(
                    f"> IPC: Removed stale socket at {uds_path} "
                    "(previous process did not shut down cleanly)"
                )
            else:
                raise RuntimeError(
                    f"Path {uds_path} exists but is not a socket "
                    f"(mode={oct(file_stat.st_mode)}). Manual intervention required."
                )
        except PermissionError as exc:
            raise RuntimeError(
                f"Cannot remove stale socket {uds_path}: {exc}. "
                "Check that yantra_daemon owns the socket."
            ) from exc


async def serve() -> None:
    """
    Async entry point. Call this from the Kriya Loop engine as a background task:

        asyncio.create_task(ipc_server.serve())

    The server binds exclusively to the UDS path. No TCP interface is created.
    Socket permissions are enforced inside the FastAPI lifespan context.
    """
    _cleanup_stale_socket(UDS_PATH)

    config = uvicorn.Config(
        app=app,
        uds=UDS_PATH,
        log_level="warning",       # Suppress uvicorn access logs in journal
        access_log=False,
        loop="asyncio",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    log.info(f"> IPC: UDS server starting — binding to {UDS_PATH}")
    await server.serve()


# ── Standalone entrypoint (for testing) ──────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    asyncio.run(serve())
