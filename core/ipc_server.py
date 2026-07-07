import logging
import asyncio
import os
import time
from fastapi import APIRouter, Request, HTTPException, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

log = logging.getLogger(__name__)

# ── Localhost enforcement for privileged endpoints ────────────────────────────
# These IPs are considered loopback / local-only origins.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _assert_localhost(request: Request) -> None:
    """Reject non-loopback callers with 403 Forbidden.
    
    Privileged endpoints (secrets injection, route mutation) MUST only be
    callable from the local machine. This is a defense-in-depth guard —
    even if uvicorn is accidentally bound to 0.0.0.0 in the future, these
    endpoints remain inaccessible to remote hosts.
    """
    client_host = request.client.host if request.client else None
    if client_host not in _LOOPBACK_HOSTS:
        log.warning(
            f"> SECURITY: Rejected privileged request from non-local host {client_host}"
        )
        raise HTTPException(
            status_code=403,
            detail="Privileged endpoint restricted to localhost only."
        )


# Rigid Pydantic models with extra="forbid" for Data Minimization (DPDPA Section 8)
# Compatible with both Pydantic v1 and v2 via 'class Config:'
class TelemetryHeartbeat(BaseModel):
    class Config:
        extra = "forbid"
    
    # Expected fields based on yantraos/telemetry/v1 schema
    daemon_status: Optional[str] = None
    active_model: Optional[str] = None
    inference_routing: Optional[str] = None
    status: Optional[str] = None
    iteration: Optional[int] = None

class InjectCommand(BaseModel):
    class Config:
        extra = "forbid"
    
    command: Optional[str] = None
    instruction: Optional[str] = None
    task: Optional[str] = None

class RouteConfig(BaseModel):
    class Config:
        extra = "forbid"
    
    tier: str
    model: str

class SecretUpdate(BaseModel):
    class Config:
        extra = "forbid"
    
    provider: str
    key: str

def attach_ipc_routes(app: FastAPI, engine_ref) -> None:
    """
    Attach strict IPC routes to the FastAPI application.
    Rejects any payload containing undocumented keys.
    Privileged endpoints enforce localhost-only access.
    """
    
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
            stdout_b, _ = await proc.communicate()
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

    @app.post("/telemetry/heartbeat", response_model_exclude_unset=True)
    async def heartbeat(payload: TelemetryHeartbeat):
        # Strict validation passes; process heartbeat
        return {"status": "ok"}

    @app.post("/inject", response_model_exclude_unset=True)
    async def inject(payload: InjectCommand):
        # Extract command safely after strict validation
        cmd = payload.command or payload.instruction or payload.task
        if not cmd:
            return JSONResponse(status_code=400, content={"error": "Missing 'command' field"})
        
        if cmd == "CONSENT_REVOKED":
            engine_ref.compliance_executor.record_consent("CONSENT_REVOKED")
            log.info("> STATE API: Consent revoked, data purge triggered.")
            return {"status": "accepted", "command": cmd, "action": "purged"}
            
        # Inject into the Kriya Loop engine
        engine_ref._pending_injections.append(str(cmd))
        log.info(f"> STATE API: Injected user task: {cmd}")
        return {"status": "accepted", "command": cmd}

    @app.post("/api/v1/config/route", response_model_exclude_unset=True)
    async def route_config(request: Request, payload: RouteConfig):
        _assert_localhost(request)
        tier = payload.tier
        model = payload.model
        if tier not in ["traffic_cop", "heavy_lifter"] or not model:
            return JSONResponse(status_code=400, content={"error": "Invalid tier or missing model"})
        
        if hasattr(engine_ref, "_config") and hasattr(engine_ref._config, "models"):
            engine_ref._config.models[tier] = str(model)
            return {"status": "success", "tier": tier, "model": model}
        
        return JSONResponse(status_code=500, content={"error": "Engine config not available"})

    @app.post("/api/v1/secrets/update", response_model_exclude_unset=True)
    async def update_secrets(request: Request, payload: SecretUpdate):
        _assert_localhost(request)
        provider = payload.provider
        key = payload.key
        
        action = {
            "type": "UPDATE_SECRETS",
            "reason": f"C2 requested ephemeral secret injection for {provider}",
            "target": f"{provider}={key}"
        }
        engine_ref._state.pending_actions.append(action)
        return {"status": "success", "message": f"Queued privileged UPDATE_SECRETS for {provider}"}

    @app.get("/notifications")
    async def get_notifications():
        notifications = list(engine_ref._state.notifications)
        engine_ref._state.notifications.clear()
        return JSONResponse(content={"notifications": notifications})
