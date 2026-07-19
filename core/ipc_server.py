import asyncio
import hmac
import json
import logging
import os
import re
import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

log = logging.getLogger(__name__)

_LOCAL_AUTHORITY = re.compile(
    r"(?:(?:localhost|127\.0\.0\.1)(?::([0-9]{1,5}))?|\[::1\](?::([0-9]{1,5}))?)\Z",
    re.IGNORECASE,
)
MAX_REQUEST_BODY_BYTES = 8192
MAX_PENDING_INJECTIONS = 10
MAX_NOTIFICATION_COUNT = 10
MAX_NOTIFICATION_CHARS = 4096
MAX_NOTIFICATION_RESPONSE_BYTES = 16 * 1024
SNAPPER_TIMEOUT_SECONDS = 5


def _is_local_authority(authority: str) -> bool:
    match = _LOCAL_AUTHORITY.fullmatch(authority)
    if not match:
        return False
    port = match.group(1) or match.group(2)
    return port is None or 0 < int(port) <= 65535


def _is_local_origin(origin: str) -> bool:
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(origin)
        parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and _is_local_authority(parsed.netloc)
    )


def _notification_payload_size(notifications: list[str]) -> int:
    return len(
        json.dumps(
            {"notifications": notifications},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


class InjectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: StrictStr = Field(min_length=1, max_length=500)

    @field_validator("command")
    @classmethod
    def reject_controls(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("command must not contain control characters")
        return value


def attach_ipc_routes(app: FastAPI, engine_ref) -> None:
    """
    Attach strict IPC routes to the FastAPI application.
    Reject undocumented payload keys and authenticate the control plane.
    """
    control_token = os.getenv("YANTRA_CONTROL_TOKEN")
    if (
        not control_token
        or len(control_token) < 32
        or control_token.startswith("<")
        or not control_token.isprintable()
        or any(character.isspace() for character in control_token)
    ):
        control_token = None
    control_token_bytes = control_token.encode("utf-8") if control_token else None
    if control_token_bytes is None:
        log.error("> STATE API: YANTRA_CONTROL_TOKEN is not configured; control routes disabled.")

    @app.middleware("http")
    async def guard_control_plane(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        allowed_clients = {"127.0.0.1", "::1", "localhost"}
        if os.getenv("YANTRA_TEST_MODE") == "1":
            allowed_clients.add("testclient")
        if request.client is None or request.client.host not in allowed_clients:
            return JSONResponse(status_code=403, content={"detail": "Remote clients are forbidden."})

        hosts = request.headers.getlist("host")
        if len(hosts) != 1 or not _is_local_authority(hosts[0]):
            return JSONResponse(status_code=403, content={"detail": "Invalid Host header."})

        origins = request.headers.getlist("origin")
        if origins and (len(origins) != 1 or not _is_local_origin(origins[0])):
            return JSONResponse(status_code=403, content={"detail": "Invalid Origin header."})

        if control_token_bytes is None:
            return JSONResponse(
                status_code=503,
                content={"detail": "Control API is not configured."},
            )

        authorization = request.headers.getlist("authorization")
        supplied = b""
        valid_scheme = False
        if len(authorization) == 1:
            scheme, separator, token = authorization[0].partition(" ")
            valid_scheme = bool(separator and token and " " not in token and scheme.lower() == "bearer")
            supplied = token.encode("utf-8")
        if not valid_scheme or not hmac.compare_digest(supplied, control_token_bytes):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid control credentials."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        content_lengths = request.headers.getlist("content-length")
        if len(content_lengths) > 1:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length."})
        if content_lengths:
            try:
                if int(content_lengths[0]) < 0 or int(content_lengths[0]) > MAX_REQUEST_BODY_BYTES:
                    return JSONResponse(status_code=413, content={"detail": "Request body too large."})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length."})
        if len(await request.body()) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body too large."})

        return await call_next(request)

    @app.get("/debug")
    async def get_debug():
        import subprocess

        if os.getenv("YANTRA_DEBUG_API") != "1":
            raise HTTPException(status_code=403, detail="Debug API is disabled.")

        diag = {}
        
        # Report subsystem state without exposing secret names, lengths, or paths.
        try:
            router = engine_ref._router
            diag["router_local_only"] = getattr(router, "local_only_mode", "N/A")
            diag["router_last_tier"] = getattr(router, "last_routing_tier", "N/A")
        except Exception as e:
            diag["router_state"] = f"ERROR: {e}"
        
        # Journal output can contain task data; debug mode is explicitly opt-in.
        try:
            out = subprocess.check_output(
                ["journalctl", "-u", "yantra.service", "-n", "50", "--no-pager"],
                text=True, timeout=5
            )
            diag["journal_tail"] = out[-2000:] if len(out) > 2000 else out
        except Exception as e:
            diag["journal"] = f"ERROR: {e}"
        
        return JSONResponse(content=diag)

    @app.get("/state")
    async def get_state():
        s = engine_ref._state
        uptime = round(time.time() - s.start_time)
        
        btrfs_snapshot_id = "N/A"
        btrfs_timestamp = "N/A"
        try:
            proc = await asyncio.create_subprocess_exec(
                "snapper", "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout_b, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=SNAPPER_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.communicate()
                raise
            if proc.returncode == 0:
                lines = stdout_b.decode().strip().split('\n')
                if len(lines) > 2:
                    last_line = lines[-1].split('|')
                    if len(last_line) >= 3:
                        btrfs_snapshot_id = last_line[0].strip()
                        btrfs_timestamp = last_line[2].strip()
        except Exception:
            pass
        
        payload = {
            "daemon_status": "ACTIVE" if engine_ref._running else "IDLE",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "iteration": s.iteration,
            "phase": s.phase.value,
            "uptime_seconds": uptime,
            "active_model": s.active_model,
            "inference_routing": s.inference_routing,
            "cpu_pct": s.cpu_pct,
            "disk_free_gb": s.disk_free_gb,
            "vram_used_gb": s.vram_used_gb,
            "vram_total_gb": s.vram_total_gb,
            "gpu_util_pct": s.gpu_util_pct,
            "consecutive_failures": s.consecutive_failures,
            "blocked_ips": s.blocked_ips[-50:],  # last 50
            "thought_stream": s.thought_stream[-30:],  # last 30 entries
            "btrfs_snapshot_id": btrfs_snapshot_id,
            "btrfs_timestamp": btrfs_timestamp,
        }
        return JSONResponse(content=payload)

    @app.post("/inject", response_model_exclude_unset=True)
    async def inject(payload: InjectCommand):
        cmd = payload.command
        if cmd in {"CONSENT_GRANTED", "CONSENT_REVOKED"}:
            engine_ref.compliance_executor.record_consent(cmd)
            remote_purge = None
            if cmd == "CONSENT_REVOKED":
                engine_ref._pending_injections.clear()
                engine_ref._state.conversation_history.clear()
                engine_ref._state.notifications.clear()
                engine_ref._state.thought_stream.clear()
                from .cloud import revoke_telemetry

                remote_purge = await revoke_telemetry()
                log.info("> STATE API: Consent revoked, local data purge triggered.")
            return {
                "status": "accepted",
                "consent": cmd,
                "remote_purge": remote_purge,
            }

        if len(engine_ref._pending_injections) >= MAX_PENDING_INJECTIONS:
            return JSONResponse(
                status_code=429,
                content={"detail": "Injection queue is full."},
                headers={"Retry-After": "10"},
            )

        engine_ref._pending_injections.append(cmd)
        log.info("> STATE API: Accepted user task for injection.")
        return {"status": "accepted"}

    @app.post("/notifications")
    async def consume_notifications():
        queue = engine_ref._state.notifications
        notifications: list[str] = []
        consumed = 0
        for raw_notification in queue[:MAX_NOTIFICATION_COUNT]:
            text = str(raw_notification)[:MAX_NOTIFICATION_CHARS]
            if _notification_payload_size(notifications + [text]) > MAX_NOTIFICATION_RESPONSE_BYTES:
                low, high = 0, len(text)
                while low < high:
                    middle = (low + high + 1) // 2
                    if _notification_payload_size(notifications + [text[:middle]]) <= MAX_NOTIFICATION_RESPONSE_BYTES:
                        low = middle
                    else:
                        high = middle - 1
                text = text[:low]
            if _notification_payload_size(notifications + [text]) > MAX_NOTIFICATION_RESPONSE_BYTES:
                break
            notifications.append(text)
            consumed += 1

        del queue[:consumed]
        return JSONResponse(content={"notifications": notifications})
