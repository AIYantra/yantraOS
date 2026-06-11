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
import platform
import socket
import time
import pathlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

import psutil
from dotenv import dotenv_values, load_dotenv

from core.ota_manager import OTAManager, OTAUpdateError

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("yantra.ipc_server")

_SCRIPT_DIR = pathlib.Path(__file__).parent

# ── Configuration path matrix ─────────────────────────────────────────────────
# READ path  — root:root 0600 canonical reference (EnvironmentFile= historically)
_SECRETS_PATH_SYSTEM = pathlib.Path("/etc/yantra/host_secrets.env")
# WRITE path — root:yantra 0660, inside the 0770 root:yantra writable zone
#              yantra_daemon gains write access via group membership (no UID 0 needed)
_SECRETS_PATH_WRITABLE = pathlib.Path("/etc/yantra/writable/host_secrets.env")
# DEV fallback — repo-root host_secrets.env, used when neither system path exists
_SECRETS_PATH_DEV = _SCRIPT_DIR.parent / "host_secrets.env"

_KEY_ALLOWLIST = {"GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "YANTRA_DAEMON_KEY"}
_AVAILABLE_MODELS = [
    "local/llama3",
    "gemini/gemini-2.5-flash",
    "gemini/gemini-2.0-flash",
    "openai/gpt-4o",
    "anthropic/claude-3-5-sonnet",
]

# Shell metacharacters and control characters that must never appear in env values.
# An attacker injecting these into the .env file could break EnvironmentFile= parsing
# or cause command injection if a wrapper script evaluates the file with `source`.
_ENV_FORBIDDEN_CHARS: frozenset[str] = frozenset(
    "\n\r\x00\t"
    "`$!;|&(){}[]\\"
    "'\"<>"
)
_MAX_ENV_VALUE_LEN = 1024  # hard ceiling — no credential exceeds 1 KiB


def _secrets_path() -> pathlib.Path:
    """Return the best READABLE secrets env file.

    Priority:
      1. Writable system path (live system, both readable and writable by daemon)
      2. Read-only system path (live system, daemon has read but not write)
      3. Dev fallback (repo root, for local development only)
    """
    if _SECRETS_PATH_WRITABLE.exists() and os.access(_SECRETS_PATH_WRITABLE, os.R_OK):
        return _SECRETS_PATH_WRITABLE
    if _SECRETS_PATH_SYSTEM.exists() and os.access(_SECRETS_PATH_SYSTEM, os.R_OK):
        return _SECRETS_PATH_SYSTEM
    return _SECRETS_PATH_DEV


def _writable_secrets_path() -> pathlib.Path:
    """Return the path the daemon has WRITE permission to.

    On a live system this is /etc/yantra/writable/host_secrets.env (0660 root:yantra).
    In dev this falls back to the repo-root host_secrets.env.
    """
    if _SECRETS_PATH_WRITABLE.parent.exists() and os.access(
        _SECRETS_PATH_WRITABLE.parent, os.W_OK
    ):
        return _SECRETS_PATH_WRITABLE
    return _SECRETS_PATH_DEV


def _sanitize_env_value(key: str, value: str) -> str:
    """Validate and sanitize a single environment variable value.

    Raises ValueError if the value contains forbidden characters or exceeds
    the maximum allowed length.  The key name is passed only for error messages.

    Security invariants enforced:
      • No newline / carriage-return / null bytes — prevent env-file splitting
        and C-string truncation attacks.
      • No shell metacharacters (\\ ` $ ! ; | & etc.) — prevent source-injection
        if a wrapper evaluates the file with `source` or `eval`.
      • No quote characters (both single and double) — prevent quoting bypass.
      • Length capped at 1024 bytes — no credential exceeds this in practice;
        prevents memory exhaustion via enormous synthetic key values.
    """
    if not isinstance(value, str):
        raise ValueError(f"{key}: value must be a string, got {type(value).__name__}")
    if len(value) > _MAX_ENV_VALUE_LEN:
        raise ValueError(
            f"{key}: value length {len(value)} exceeds maximum {_MAX_ENV_VALUE_LEN} characters"
        )
    bad = [c for c in value if c in _ENV_FORBIDDEN_CHARS]
    if bad:
        printable = [repr(c) for c in bad]
        raise ValueError(
            f"{key}: value contains forbidden character(s): {', '.join(printable)}"
        )
    return value


def _mask_key(value: str) -> str:
    if len(value) <= 8:
        return "********"
    return value[:4] + "..." + value[-4:]


# ── Shared state reference (injected by engine.py at startup) ─────────────────
_state_ref: object | None = None
_active_streaming_queues: set[asyncio.Queue[str]] = set()

# ── GATE 3: Shared concurrency lock (injected by engine.py) ──────────────────
_state_lock: asyncio.Lock | None = None


def set_state_ref(state: object) -> None:
    """Inject a live KriyaState reference into the web server module."""
    global _state_ref
    _state_ref = state
    log.info("> WEB: State reference registered.")


def set_state_lock_ref(lock: asyncio.Lock) -> None:
    """Inject the shared asyncio.Lock for state mutation serialization."""
    global _state_lock
    _state_lock = lock
    log.info("> WEB: State lock reference registered.")


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
                    "vram_pct": round(vram_pct, 1),
                    "phase": getattr(_state_ref, "phase", "SENSE"),
                    # ── RC3: Deep telemetry fields for TUI/Wayland HUD ────
                    # Raw numerical arrays — no UI processing, no CSS.
                    # The Brutalist TUI parses these directly.
                    "vram_allocation_mb": int(getattr(_state_ref, "vram_allocation_mb", 0)),
                    "inference_tps": round(float(getattr(_state_ref, "inference_tps", 0.0)), 2),
                    "context_window_tokens": int(getattr(_state_ref, "context_window_tokens", 0)),
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

# ── CORS: restrict to localhost only (block remote frame injection) ───────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:50000",
        "http://localhost:50000",
        "http://127.0.0.1",
        "http://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static assets: mount Vite build output (core/web/) → /assets ────────────
# Vite emits hashed JS/CSS chunks into core/web/assets/.  We mount that
# sub-directory at /assets so the HTML <script src="/assets/..."> tags resolve.
_static_dir = pathlib.Path(__file__).parent / "web"
_assets_dir = _static_dir / "assets"
try:
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")
        log.info(f"> WEB: Vite assets mounted from {_assets_dir}")
    elif _static_dir.exists():
        # Fallback: mount whole directory (plain HTML deployment without Vite assets/)
        app.mount("/assets", StaticFiles(directory=str(_static_dir)), name="assets")
        log.info(f"> WEB: Static files mounted (no assets/ sub-dir) from {_static_dir}")
    else:
        log.warning(f"> WEB: Static dir not found — asset endpoint inactive ({_static_dir})")
except Exception as _e:
    log.error(f"> WEB: Failed to mount static files: {_e}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_dashboard():
    """Serve the Vite-compiled React SPA entry point."""
    index_path = pathlib.Path(__file__).parent / "web" / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html")
    return JSONResponse({"error": "Dashboard not built — run 'npm run build' in frontend_src/"}, status_code=404)




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
        # ── RC3: Deep telemetry fields for TUI/Wayland HUD ────────────
        "vram_allocation_mb": int(getattr(s, "vram_allocation_mb", 0)),
        "inference_tps": round(float(getattr(s, "inference_tps", 0.0)), 2),
        "context_window_tokens": int(getattr(s, "context_window_tokens", 0)),
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
            if _state_lock:
                async with _state_lock:
                    _state_ref.shutdown_requested = True  # type: ignore[attr-defined]
            else:
                _state_ref.shutdown_requested = True  # type: ignore[attr-defined]
            log.info("> WEB: Shutdown requested via /command endpoint.")
        return JSONResponse({"status": "shutdown_requested"})

    if action == "pause":
        if _state_ref is not None:
            if _state_lock:
                async with _state_lock:
                    _state_ref.is_paused = True  # type: ignore[attr-defined]
            else:
                _state_ref.is_paused = True  # type: ignore[attr-defined]
            log.info("> WEB: Kriya Loop PAUSED via /command endpoint.")
        return JSONResponse({"status": "paused"})

    if action == "resume":
        if _state_ref is not None:
            if _state_lock:
                async with _state_lock:
                    _state_ref.is_paused = False  # type: ignore[attr-defined]
            else:
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
            if _state_lock:
                async with _state_lock:
                    _state_ref.injected_thoughts.append(payload)  # type: ignore[attr-defined]
            else:
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
            if _state_lock:
                async with _state_lock:
                    _state_ref.active_model      = model        # type: ignore[attr-defined]
                    _state_ref.inference_routing = route        # type: ignore[attr-defined]
            else:
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


@app.get("/api/config")
async def get_config():
    """Return current daemon config with masked API key values."""
    try:
        sp = _secrets_path()
        secrets = dotenv_values(str(sp)) if sp.exists() else {}
    except (PermissionError, OSError) as exc:
        log.warning(f"> WEB: Cannot read secrets file: {exc}")
        secrets = {}
    masked_keys = {k: _mask_key(v) if v else "" for k, v in secrets.items() if k in _KEY_ALLOWLIST}
    for k in _KEY_ALLOWLIST:
        masked_keys.setdefault(k, "")

    s = _state_ref
    return JSONResponse({
        "api_keys": masked_keys,
        "inference": {
            "routing": getattr(s, "inference_routing", "LOCAL") if s else "LOCAL",
            "active_model": getattr(s, "active_model", "local/llama3") if s else "local/llama3",
            "available_models": _AVAILABLE_MODELS,
        },
        "daemon": {
            "status": "ACTIVE" if s else "OFFLINE",
            "is_paused": bool(getattr(s, "is_paused", False)) if s else False,
            "iteration": int(getattr(s, "iteration", 0)) if s else 0,
            "uptime_seconds": int(time.time() - psutil.boot_time()),
        },
    })


@app.post("/api/config")
async def post_config(request: Request):
    """Write partial config updates with hardened input sanitization.

    API keys are written atomically to the daemon-writable secrets path
    (/etc/yantra/writable/host_secrets.env on a live system, repo-root
    host_secrets.env in dev).  Inference routing overrides are applied to
    the in-process KriyaState reference.

    Security guarantees:
      • Only keys in _KEY_ALLOWLIST are accepted — arbitrary env injection blocked.
      • All values are validated by _sanitize_env_value() before any I/O:
          – Shell metacharacters stripped (\n \r \x00 ` $ ; | & etc.)
          – Quote characters rejected
          – Max 1024 characters per value
      • File is written via O_WRONLY|O_CREAT with fchmod(0o660) before data
        is written — the mode is enforced at fd level, not after-the-fact chmod.
      • Atomic rename(): the live file is never partially written; readers
        either see the old or the new content, never a torn write.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    updated: list[str] = []

    # ── API key writes ────────────────────────────────────────────────────────
    api_keys: dict = body.get("api_keys", {})
    if api_keys:
        # 1. Validate ALL keys and values up-front before touching the filesystem.
        #    Any violation aborts the entire write — no partial updates.
        sanitized: dict[str, str] = {}
        for key, value in api_keys.items():
            # 1a. Key name must be in the allowlist — no arbitrary env injection.
            if key not in _KEY_ALLOWLIST:
                return JSONResponse(
                    {"error": f"Key not in allowlist: {key}"},
                    status_code=400,
                )
            # 1b. Value must pass the sanitizer (type, length, forbidden chars).
            try:
                sanitized[key] = _sanitize_env_value(key, str(value) if value is not None else "")
            except ValueError as exc:
                return JSONResponse(
                    {"error": f"Validation failed: {exc}"},
                    status_code=400,
                )

        # 2. Resolve the writable path. On a live system this is the 0660 group-writable
        #    file inside /etc/yantra/writable/; in dev it is the repo-root fallback.
        wp = _writable_secrets_path()

        # 3. Load the existing key=value pairs (if the file exists) so we merge,
        #    not overwrite, unrelated keys.
        existing: dict[str, str] = {}
        read_path = _secrets_path()
        if read_path.exists():
            try:
                existing = dict(dotenv_values(str(read_path)))
            except (PermissionError, OSError) as exc:
                log.warning(f"> WEB: Cannot read existing secrets for merge: {exc}")

        # 4. Merge sanitized values into the existing map.
        for key, value in sanitized.items():
            existing[key] = value
            updated.append(key)

        # 5. Serialise to env-file format.  Values are double-quoted; the sanitizer
        #    already guarantees no embedded double-quotes or newlines in the value.
        lines = "\n".join(f'{k}="{v}"' for k, v in existing.items()) + "\n"

        # 6. Atomic write with enforced 0660 mode:
        #      • os.open() with O_WRONLY|O_CREAT|O_TRUNC creates or truncates.
        #      • mode=0o660 is the CREATE-time permission; we fchmod immediately
        #        after open so the mode is set before any bytes land on disk.
        #        This prevents a race where another process reads a 0644 temp file.
        #      • os.rename() is a single syscall — POSIX-atomic on the same device.
        try:
            wp.parent.mkdir(parents=True, exist_ok=True)
            tmp = wp.with_suffix(".env.tmp")
            fd = os.open(
                str(tmp),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o660,   # create-time mode — honours umask, so we fchmod below
            )
            try:
                os.fchmod(fd, 0o660)          # enforce 0660 regardless of process umask
                with os.fdopen(fd, "w") as fh:
                    fh.write(lines)
                fd = -1                        # fdopen took ownership; do not double-close
            finally:
                if fd != -1:                   # write failed before fdopen — close the raw fd
                    os.close(fd)
            os.replace(str(tmp), str(wp))      # atomic inode swap
            load_dotenv(str(wp), override=True)
            log.info(f"> WEB: Secrets written atomically to {wp} (keys: {updated})")
        except (PermissionError, OSError) as exc:
            log.error(f"> WEB: Failed to write secrets to {wp}: {exc}")
            return JSONResponse(
                {"error": f"Permission denied writing secrets: {exc}"},
                status_code=500,
            )

    # ── Inference routing / model override ───────────────────────────────────
    inference: dict = body.get("inference", {})
    if inference and _state_ref is not None:
        routing = inference.get("routing")
        model   = inference.get("active_model")
        if routing or model:
            if _state_lock:
                async with _state_lock:
                    if routing: _state_ref.inference_routing = routing  # type: ignore[attr-defined]
                    if model:   _state_ref.active_model      = model    # type: ignore[attr-defined]
            else:
                if routing: _state_ref.inference_routing = routing  # type: ignore[attr-defined]
                if model:   _state_ref.active_model      = model    # type: ignore[attr-defined]
            if routing: updated.append("inference.routing")
            if model:   updated.append("inference.active_model")

    return JSONResponse({"status": "ok", "updated": updated})


@app.get("/api/system")
async def get_system():
    """Return system identity info: hostname, OS, kernel, uptime, IP."""
    uname = platform.uname()
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "127.0.0.1"
    return JSONResponse({
        "hostname": uname.node,
        "os": f"{uname.system} {uname.release}",
        "kernel": uname.version,
        "machine": uname.machine,
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "ip": ip,
    })


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


# ── SPA catch-all: React Router deep-link support ─────────────────────────────
# MUST be the last GET route registered. FastAPI matches routes in registration
# order; placing this last ensures /health, /telemetry, /api/*, /command, and
# /stream all resolve to their dedicated handlers before the catch-all fires.
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """Catch-all fallback: return index.html for all non-API GET requests."""
    # Serve real static files that Vite placed in public/ (favicon, manifest, etc.).
    static_file = pathlib.Path(__file__).parent / "web" / full_path
    if static_file.is_file():
        return FileResponse(static_file)
    # Fall back to SPA shell for all React Router client-side routes.
    index_path = pathlib.Path(__file__).parent / "web" / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html")
    return JSONResponse({"error": "Dashboard not built — run 'npm run build' in frontend_src/"}, status_code=404)


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
