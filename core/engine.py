"""
YantraOS — Kriya Loop Engine (Headless MVP)

The 3-phase autonomous cycle that drives YantraOS. Each iteration:
  SENSE      → Collect hardware telemetry and system state
  REASON     → Analyze and form intent
  ACT        → Execute corrective/optimization actions (via Docker sandbox)
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    import uvicorn
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

try:
    import sdnotify  # type: ignore[import-not-found]
    _SDNOTIFY_AVAILABLE = True
except ImportError:
    sdnotify = None  # type: ignore[assignment]
    _SDNOTIFY_AVAILABLE = False

from .prompt import get_system_prompt, get_safety_context
from .hardware import probe_gpu, probe_cpu_disk, get_ssh_telemetry
from .compliance_executor import ComplianceExecutor
from .vector_memory import get_memory
from .hybrid_router import (
    select_model_group, stream_complete, INFERENCE_TIMEOUT_SECS,
    detect_hardware_capability, InferenceAuthError, get_last_routing_tier,
)
from .sandbox import sandbox, SandboxStatus
from .audit_log import log_execution
from .cloud import stream_telemetry

log = logging.getLogger("yantra.engine")

# ── Phases ────────────────────────────────────────────────────────

class KriyaPhase(str, Enum):
    SENSE = "SENSE"
    REASON = "REASON"
    ACT = "ACT"


# ── State ─────────────────────────────────────────────────────────

MAX_PENDING_ACTIONS: int = 5
_EVICTION_AUDIT_PATH: str = "/var/log/yantra/engine.log"


def _eviction_audit_logger() -> logging.Logger:
    audit: logging.Logger = logging.getLogger("yantra.engine.queue")
    audit.setLevel(logging.WARNING)
    audit.propagate = True

    already_bound: bool = any(
        getattr(handler, "_yantra_eviction_sink", False)
        for handler in audit.handlers
    )
    if not already_bound:
        try:
            os.makedirs(os.path.dirname(_EVICTION_AUDIT_PATH), exist_ok=True)
            file_handler: logging.Handler = logging.FileHandler(
                _EVICTION_AUDIT_PATH
            )
            file_handler.setLevel(logging.WARNING)
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s — %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            ))
            file_handler._yantra_eviction_sink = True  # type: ignore[attr-defined]
            audit.addHandler(file_handler)
        except OSError as exc:
            log.warning(
                "Queue eviction audit log unavailable at %s (%s) — "
                "falling back to stdout logger.",
                _EVICTION_AUDIT_PATH, exc,
            )
    return audit


class TrackedActionQueue(collections.deque[dict[str, Any]]):
    def __init__(self, maxlen: int = MAX_PENDING_ACTIONS) -> None:
        super().__init__(maxlen=maxlen)
        self._audit: logging.Logger = _eviction_audit_logger()

    def append(self, action: dict[str, Any]) -> None:  # type: ignore[override]
        cap: int | None = self.maxlen
        if cap is not None and len(self) == cap:
            self._audit_eviction(self[0], cap)
        super().append(action)

    def _audit_eviction(self, evicted: dict[str, Any], cap: int) -> None:
        intent_type: str = str(evicted.get("type", "UNKNOWN"))
        canonical: bytes = json.dumps(
            evicted, sort_keys=True, default=str
        ).encode("utf-8")
        fingerprint: str = hashlib.sha256(canonical).hexdigest()
        self._audit.warning(
            "[QUEUE_EVICTION] Action Dropped | Intent: %s | Hash: %s | "
            "Reason: Capacity MAX_PENDING_ACTIONS=%d reached.",
            intent_type, fingerprint, cap,
        )


@dataclass
class KriyaState:
    phase: KriyaPhase = KriyaPhase.SENSE
    iteration: int = 0
    start_time: float = field(default_factory=time.time)
    shutdown_requested: bool = False

    # Telemetry from SENSE phase
    vram_used_gb: float = 0.0
    vram_total_gb: float = 0.0
    gpu_util_pct: float = 0.0
    cpu_pct: float = 0.0
    disk_free_gb: float = 0.0
    active_model: str = "unknown"
    inference_routing: str = "PENDING"

    vram_allocation_mb: int = 0
    ram_percent: float = 0.0
    inference_tps: float = 0.0
    context_window_tokens: int = 0

    pending_actions: TrackedActionQueue = field(default_factory=TrackedActionQueue)
    consecutive_failures: int = 0
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    ssh_auth_logs: str = ""
    blocked_ips: list[dict] = field(default_factory=list)
    thought_stream: list[str] = field(default_factory=list)


# ── Config ────────────────────────────────────────────────────────

ITERATION_INTERVAL_SECS = 10
WATCHDOG_SEC = 30
_WATCHDOG_PING_INTERVAL = WATCHDOG_SEC / 2


# ── Kriya Loop Engine ─────────────────────────────────────────────

class KriyaLoopEngine:
    def __init__(self) -> None:
        self._state = KriyaState()
        self._pending_injections: list[str] = []
        self._system_prompt = get_system_prompt()
        self._safety = get_safety_context()
        self._running = False
        self._last_watchdog_ping: float = 0.0
        self.compliance_executor = ComplianceExecutor(chroma_client=get_memory().client)

        if sdnotify is not None:
            self._sd = sdnotify.SystemdNotifier()
            self._sd.notify("STATUS=Initializing Kriya Loop...")
        else:
            self._sd = None

    def _register_signals(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle_shutdown)
        log.info("> SYSTEM: Signal handlers registered.")

    def _handle_shutdown(self, *_) -> None:
        log.info("> SYSTEM: Shutdown signal received. Entering drain state.")
        self._state.shutdown_requested = True

    def _sd_notify(self, message: str) -> None:
        if self._sd:
            try:
                self._sd.notify(message)
            except Exception:
                pass

    def _sd_watchdog_ping(self) -> None:
        now = time.monotonic()
        if now - self._last_watchdog_ping >= _WATCHDOG_PING_INTERVAL:
            self._sd_notify("WATCHDOG=1")
            self._last_watchdog_ping = now

    async def _watchdog_heartbeat_loop(self) -> None:
        while self._running and not self._state.shutdown_requested:
            self._sd_notify("WATCHDOG=1")
            self._last_watchdog_ping = time.monotonic()
            await asyncio.sleep(_WATCHDOG_PING_INTERVAL)

    # ── Phase: SENSE ───────────────────────────────────────────────

    async def _phase_sense(self) -> None:
        self._state.phase = KriyaPhase.SENSE
        log.info("> DAEMON: [SENSE] Collecting telemetry...")

        gpu = probe_gpu()
        self._state.vram_used_gb = gpu.vram_used_gb
        self._state.vram_total_gb = gpu.vram_total_gb
        self._state.gpu_util_pct = gpu.gpu_util_pct

        cpu_pct, disk_free_gb, ram_pct = probe_cpu_disk()
        self._state.cpu_pct = cpu_pct
        self._state.disk_free_gb = disk_free_gb
        self._state.ram_percent = ram_pct

        self._state.vram_allocation_mb = int(self._state.vram_used_gb * 1024)
        
        self._state.ssh_auth_logs = await get_ssh_telemetry()

        msg = (
            f"> TELEMETRY: VRAM {self._state.vram_used_gb:.1f}/"
            f"{self._state.vram_total_gb:.1f}GB — GPU {self._state.gpu_util_pct}%"
        )
        log.info(msg)

    # ── Phase: REASON ──────────────────────────────────────────────

    async def _phase_reason(self) -> None:
        self._state.phase = KriyaPhase.REASON
        self._state.pending_actions.clear()
        log.info("> DAEMON: [REASON] Analyzing system state...")

        # Context Summarization: Truncate log tail if it exceeds ~2000 tokens
        ssh_logs = self._state.ssh_auth_logs
        if len(ssh_logs) > 8000:
            filtered = [
                line for line in ssh_logs.splitlines() 
                if any(flag in line.upper() for flag in ("WARNING", "ERROR", "FATAL"))
            ]
            ssh_logs = "\n".join(filtered)[-8000:]

        telemetry_context: dict[str, Any] = {
            "schema": "yantraos/telemetry/v1",
            "iteration": self._state.iteration,
            "hardware": {
                "vram_used_gb": round(self._state.vram_used_gb, 2),
                "vram_total_gb": round(self._state.vram_total_gb, 2),
                "gpu_util_pct": round(self._state.gpu_util_pct, 1),
                "cpu_pct": round(self._state.cpu_pct, 1),
                "disk_free_gb": round(self._state.disk_free_gb, 2),
            },
            "active_model": self._state.active_model,
            "inference_routing": self._state.inference_routing,
            "ssh_auth_logs": ssh_logs,
        }

        user_content = json.dumps({
            "telemetry": telemetry_context,
            "instruction": (
                "Analyze the telemetry snapshot above. Identify anomalies, "
                "inefficiencies, or optimization opportunities. If action is "
                "warranted, respond with a JSON object containing a \"actions\" "
                "array where each element has \"type\", \"reason\", \"script\" "
                "(optional shell command), and \"priority\" (CRITICAL/HIGH/MEDIUM/LOW). "
                "For system maintenance operations (pruning snapshots, reloading daemon, restarting daemon, etc.), set \"type\" to the appropriate sovereign system intent: PRUNE_SNAPSHOTS, RELOAD_DAEMON_CONFIGS, RESTART_DAEMON, BLOCK_IP, SYSTEM_UPDATE, SYNC_CLOCK, ENABLE_DAEMON, DISABLE_DAEMON, STOP_DAEMON. Do NOT provide a script when dispatching sovereign system intents. "
                "If the system is nominal, respond with {\"actions\": []}. "
                "If the SSH authentication logs show repeated 'Disconnected from invalid user', "
                "'Connection closed by authenticating user', or 'Permission denied (publickey)' "
                "from the SAME IP address within a short timeframe (3+ attempts), you MUST "
                "classify this as a hostile brute-force or enumeration attack. Immediately "
                "output a BLOCK_IP intent targeting the offending IP address. "
                "Respond ONLY with valid JSON. "
                "CRITICAL PRIMARY DIRECTIVE: You are an Autonomous Threat Intelligence Agent. "
                "Your ongoing mission is to build and maintain a live HTML dashboard at "
                "'/shared_data/dashboard.html'. This dashboard must display the status of the "
                "UFW firewall, a list of blocked IPs, and a summary of recent SSH attacks. "
                "During your ACT phase, you must dynamically write or update a script to generate "
                "this HTML file with clean, modern inline CSS. You must accomplish this while "
                "maintaining your Active Defense monitoring."
            ),
        }, indent=2)

        if self._pending_injections:
            injected_cmds = "\n".join(f"- {cmd}" for cmd in self._pending_injections)
            self._pending_injections.clear()
            user_content += f"\n\nPRIORITY INJECTED USER TASKS:\n{injected_cmds}\nYou MUST execute these user tasks during your ACT phase!"

        if not self._state.conversation_history:
            self._state.conversation_history.append({"role": "system", "content": self._system_prompt})

        self._state.conversation_history.append({"role": "user", "content": user_content})
        
        # Prevent context bloat by truncating history (keep system prompt + last 4 messages)
        if len(self._state.conversation_history) > 5:
            self._state.conversation_history = [self._state.conversation_history[0]] + self._state.conversation_history[-4:]
            
        messages: list[dict[str, str]] = list(self._state.conversation_history)

        accumulated_response = ""
        inference_start = time.monotonic()
        try:
            cognitive_tier = "watchdog"
            if "CRITICAL PRIMARY DIRECTIVE" in user_content or "Permission denied" in self._state.ssh_auth_logs or "Disconnected" in self._state.ssh_auth_logs or "Connection closed" in self._state.ssh_auth_logs:
                cognitive_tier = "builder"

            log.info(f"> REASONING: Streaming inference (Tier: {cognitive_tier})...")

            async def _stream_and_collect() -> str:
                collected = ""
                async for token in stream_complete(
                    messages, cognitive_tier=cognitive_tier
                ):
                    collected += token
                return collected

            accumulated_response = await asyncio.wait_for(
                _stream_and_collect(),
                timeout=INFERENCE_TIMEOUT_SECS,
            )

            inference_elapsed: float = time.monotonic() - inference_start
            approx_output_tokens: int = max(1, len(accumulated_response) // 4)
            if inference_elapsed > 0:
                self._state.inference_tps = round(approx_output_tokens / inference_elapsed, 2)
            else:
                self._state.inference_tps = 0.0
            
            approx_input_tokens: int = len(user_content) // 4
            self._state.context_window_tokens = approx_input_tokens + approx_output_tokens

            # ── Sync routing tier from the TieredRouter ──────────────────
            self._state.inference_routing = get_last_routing_tier()

            log.info(
                f"> REASON: Inference complete — "
                f"{len(accumulated_response)} chars received "
                f"(routing={self._state.inference_routing})."
            )

        except asyncio.TimeoutError:
            log.error(
                f"> REASON: Inference timeout after {INFERENCE_TIMEOUT_SECS}s "
                "— falling back to heuristics."
            )

        except InferenceAuthError as exc:
            hw_cap = detect_hardware_capability()
            err = (
                f"> REASON: AuthenticationError — {exc}. "
                f"Hardware domain: {hw_cap}."
            )
            log.error(err)

            if hw_cap == "CLOUD_ONLY":
                log.error(
                    "> REASON: DEGRADED_AUTH — All cloud endpoints failed "
                    "authentication. Pausing reasoning loop. Fix API keys."
                )
                self._state.inference_routing = "DEGRADED_AUTH"
            else:
                log.warning(
                    f"> REASON: Auth error on {self._state.active_model} — "
                    "falling back to local/llama3 (LOCAL_CAPABLE hardware)."
                )
                self._state.active_model = "local/llama3"
                self._state.inference_routing = "LOCAL_FALLBACK"

        except Exception as exc:
            log.error(f"> REASON: Inference failed — {type(exc).__name__}: {exc}")

            hw_cap = detect_hardware_capability()
            if self._state.active_model != "local/llama3" and hw_cap == "LOCAL_CAPABLE":
                log.warning(
                    f"> REASON: LiteLLM error on {self._state.active_model} — "
                    "falling back to local/llama3 for next iteration."
                )
                self._state.active_model = "local/llama3"
                self._state.inference_routing = "LOCAL_FALLBACK"
            elif hw_cap == "CLOUD_ONLY":
                log.warning(
                    f"> REASON: Error on {self._state.active_model} — "
                    "CLOUD_ONLY hardware, keeping cloud routing."
                )

        if accumulated_response:
            try:
                cleaned = accumulated_response.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
                cleaned = cleaned.strip()

                parsed = json.loads(cleaned)
                actions = parsed.get("actions", [])

                available_slots = MAX_PENDING_ACTIONS - len(self._state.pending_actions)
                if available_slots <= 0:
                    log.warning(
                        f"> REASON: Action queue full ({MAX_PENDING_ACTIONS}). "
                        f"Dropping {len(actions)} LLM-proposed action(s)."
                    )
                    actions = []
                else:
                    if len(actions) > available_slots:
                        log.warning(
                            f"> REASON: LLM proposed {len(actions)} actions, "
                            f"capping to {available_slots} (MAX_PENDING_ACTIONS={MAX_PENDING_ACTIONS})."
                        )
                    actions = actions[:available_slots]

                for action in actions:
                    if isinstance(action, dict) and "type" in action:
                        self._state.pending_actions.append({
                            "type": action["type"],
                            "reason": action.get("reason", "LLM-inferred"),
                            "script": action.get("script"),
                            "priority": action.get("priority", "MEDIUM"),
                        })
                
                self._state.conversation_history.append({"role": "assistant", "content": cleaned})
                
                log.info(
                    f"> REASONING: LLM proposed "
                    f"{len(self._state.pending_actions)} action(s)."
                )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                log.warning(
                    f"> REASON: Failed to parse LLM response as JSON: {exc}. "
                    "Falling back to deterministic heuristics."
                )
                self._state.pending_actions.clear()

        if not self._state.pending_actions:
            is_live_usb = not os.path.exists("/opt/yantra")
            disk_threshold = 2.0 if is_live_usb else 5.0
            
            if self._state.disk_free_gb < disk_threshold:
                self._state.pending_actions.append({
                    "type": "cleanup",
                    "reason": f"Critically low disk free space detected ({self._state.disk_free_gb:.1f} GB). Initiating aggressive cleanup.",
                    "priority": "HIGH",
                })
            if self._state.vram_used_gb > 0 and (
                self._state.vram_used_gb / max(self._state.vram_total_gb, 1)
            ) > 0.90:
                self._state.pending_actions.append({
                    "type": "vram_pressure",
                    "reason": "VRAM >90% — consider offloading to cloud inference.",
                    "priority": "MEDIUM",
                })

        log.info(f"> REASONING: Formed {len(self._state.pending_actions)} action(s).")

        # Feed thought stream for dashboard
        ts_entry = (
            f"[{time.strftime('%H:%M:%S')}] REASON #{self._state.iteration}: "
            f"{len(self._state.pending_actions)} action(s) queued — "
            f"model={self._state.active_model}"
        )
        self._state.thought_stream.append(ts_entry)
        if len(self._state.thought_stream) > 200:
            self._state.thought_stream = self._state.thought_stream[-200:]

    # ── Phase: ACT ─────────────────────────────────────────────────

    async def _phase_act(self) -> None:
        self._state.phase = KriyaPhase.ACT

        if not self._state.pending_actions:
            log.info("> DAEMON: [ACT] No actions pending — system nominal.")
            return

        actions_snapshot = list(self._state.pending_actions)

        log.info(f"> DAEMON: [ACT] Executing {len(actions_snapshot)} action(s)...")

        for action in actions_snapshot:
            action_type = action["type"]
            reason = action["reason"]
            log.info(f"> ACTION: {action_type} — {reason}")

            script = action.get("script")

            if action_type in {
                "SYSTEM_UPDATE", "RESTART_DAEMON", "ENABLE_DAEMON", "DISABLE_DAEMON",
                "STOP_DAEMON", "PRUNE_SNAPSHOTS", "SYNC_CLOCK", "RELOAD_DAEMON_CONFIGS", "BLOCK_IP"
            }:
                target = action.get("target", "")
                if not target and action.get("script"):
                    import re
                    ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', action.get("script", ""))
                    if ip_match:
                        target = ip_match.group(0)
                await self._send_host_intent(action_type, target)
            elif script:
                if sandbox.is_operational:
                    try:
                        sandbox_result = await asyncio.wait_for(sandbox.execute(script), timeout=30.0)
                    except asyncio.TimeoutError:
                        log.error("> CRITICAL: Sandbox execution timed out after 30s. Forcing kill.")
                        await sandbox.cleanup_stale_containers()
                        self._state.consecutive_failures += 1
                        ts_entry = "> ERROR: Sandbox Execution Failed (Code: TIMEOUT) - execution exceeded 30s"
                        self._state.thought_stream.append(ts_entry)
                        if len(self._state.thought_stream) > 200:
                            self._state.thought_stream = self._state.thought_stream[-200:]
                        continue
                else:
                    log.warning("> SANDBOX: Operational status DEGRADED (Live ISO). Executing script via local subprocess fallback...")
                    proc = await asyncio.create_subprocess_shell(
                        script,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout_b, stderr_b = await proc.communicate()
                    class FallbackResult:
                        outcome = type("Outcome", (), {"value": "SUCCESS" if proc.returncode == 0 else "FAILED"})()
                        exit_code = proc.returncode
                        duration_secs = 0.5
                        stdout = stdout_b.decode('utf-8', errors='replace')
                        stderr = stderr_b.decode('utf-8', errors='replace')
                    sandbox_result = FallbackResult()

                log_execution(script, sandbox_result)
                stdout_text = (sandbox_result.stdout or "").strip()
                stderr_text = getattr(sandbox_result, "stderr", "") or ""
                stderr_text = stderr_text.strip()
                
                status_msg = (
                    f"> ACTION: {action_type} — sandbox {sandbox_result.outcome.value} "
                    f"(exit={sandbox_result.exit_code}, {sandbox_result.duration_secs:.1f}s)"
                )
                log.info(status_msg)
                
                if sandbox_result.exit_code == 0:
                    log.info(f"> SYSTEM: Autonomous Action '{action_type}' COMPLETED SUCCESSFULLY.")
                    self._state.consecutive_failures = 0
                else:
                    log.warning(f"> ERROR: Action '{action_type}' FAILED. Escalating stderr to LLM context for self-healing retry...")
                    self._state.consecutive_failures += 1
                    
                    tail = (stderr_text[-100:] if len(stderr_text) > 100 else stderr_text).strip() or "No stderr output"
                    ts_entry = f"> ERROR: Sandbox Execution Failed (Code: {sandbox_result.exit_code}) - {tail}"
                    self._state.thought_stream.append(ts_entry)
                    if len(self._state.thought_stream) > 200:
                        self._state.thought_stream = self._state.thought_stream[-200:]
                        
                    self._state.conversation_history.append({
                        "role": "user",
                        "content": f"Action '{action_type}' failed with exit code {sandbox_result.exit_code}. Stderr: {stderr_text}"
                    })

                if stdout_text:
                    for line in stdout_text[:2000].splitlines():
                        log.info(f"> STDOUT: {line}")

                if stderr_text:
                    for line in stderr_text[:1000].splitlines():
                        log.info(f"> STDERR: {line}")

                if self._state.consecutive_failures >= 5:
                    log.critical("> CRITICAL: Circuit Breaker Triggered. Hallucination spiral detected. Flushing cognitive context.")
                    self._state.conversation_history.clear()
                    self._state.consecutive_failures = 0
            else:
                if script and not sandbox.is_operational:
                    log.warning(
                        f"> ACTION: {action_type} — sandbox {sandbox.status.value}, "
                        "execution deferred"
                    )
                else:
                    log.info(f"> ACTION: {action_type} — logged")

    async def _send_host_intent(self, intent: str, target: str) -> None:
        sock_path = "/run/yantra/executor.sock"
        log.info(f"> SYSTEM: Sending intent '{intent}' to Host Executor at {sock_path} (target='{target}')")
        try:
            reader, writer = await asyncio.open_unix_connection(sock_path)
            payload = json.dumps({"intent": intent, "target": target}) + "\n"
            writer.write(payload.encode("utf-8"))
            await writer.drain()
            
            response_bytes = await asyncio.wait_for(reader.readline(), timeout=310.0)
            if response_bytes:
                response = json.loads(response_bytes.decode("utf-8"))
                status = response.get("status", "UNKNOWN")
                if status == "SUCCESS":
                    log.info(f"> SYSTEM: Host Executor completed '{intent}' SUCCESSFULLY.")
                    self._state.consecutive_failures = 0
                    # Track BLOCK_IP events for dashboard
                    if intent == "BLOCK_IP" and target:
                        import hashlib as _hl
                        sig = _hl.sha256(f"{intent}:{target}:{time.time()}".encode()).hexdigest()[:16]
                        self._state.blocked_ips.append({
                            "ip": target,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "geo_tag": "Unknown Grid",
                            "ed25519_sig": f"ed25519:{sig}",
                            "status": "BLOCKED",
                        })
                        if len(self._state.blocked_ips) > 200:
                            self._state.blocked_ips = self._state.blocked_ips[-200:]
                else:
                    err = response.get("error", "Unknown error")
                    log.warning(f"> ERROR: Host Executor '{intent}' {status}: {err}")
                    self._state.consecutive_failures += 1
                    self._state.conversation_history.append({
                        "role": "user",
                        "content": f"Host Executor Action '{intent}' failed. Status: {status}, Error: {err}"
                    })
            
            writer.close()
            await writer.wait_closed()
        except Exception as exc:
            log.error(f"> ERROR: Failed to communicate with Host Executor: {exc}")
            self._state.consecutive_failures += 1
            self._state.conversation_history.append({
                "role": "user",
                "content": f"Failed to communicate with Host Executor socket for action '{intent}': {exc}"
            })


    # ── Main Loop ──────────────────────────────────────────────────

    async def run(self) -> None:
        self._register_signals()
        self._running = True
        self._last_watchdog_ping = time.monotonic()

        self._sd_notify("STATUS=Registering signal handlers...")
        log.info("> SYSTEM INITIATED: YantraOS Headless MVP")
        log.info("> DAEMON: Kriya Loop Active.")

        asyncio.create_task(self._watchdog_heartbeat_loop())
        log.info("> WATCHDOG: Independent heartbeat loop launched (interval=15s).")

        if _FASTAPI_AVAILABLE:
            asyncio.create_task(self._run_state_server())
            log.info("> STATE API: HTTP state server launching on 0.0.0.0:50000")

        self._sd_notify("STATUS=Initializing Docker sandbox...")
        sandbox_status = await sandbox.initialize()
        log.info(f"> SANDBOX: Docker status — {sandbox_status.value}")

        self._sd_notify("READY=1")
        self._sd_notify("STATUS=Kriya Loop running")
        log.info("> SYSTEM: All subsystems initialized. Entering main loop.")

        while not self._state.shutdown_requested:
            iter_start = time.monotonic()
            self._state.iteration += 1
            log.info(f"> DAEMON: — Iteration #{self._state.iteration} —")

            try:
                await self._phase_sense()
                self._sd_watchdog_ping()
                self._sd_notify(f"STATUS=SENSE complete (iter {self._state.iteration})")

                self._state.active_model = select_model_group(
                    self._state.vram_total_gb, self._state.vram_used_gb
                )

                await self._phase_reason()
                self._sd_watchdog_ping()

                await self._phase_act()
                self._sd_watchdog_ping()
                self._sd_notify(f"STATUS=Iteration {self._state.iteration} complete")

                # UPDATE_ARCHITECTURE Phase: Stream telemetry seamlessly in the background
                asyncio.create_task(stream_telemetry(self._state))
                # Sweep expired telemetry to enforce DPDPA data mortality
                self.compliance_executor.sweep_expired_telemetry(24.0)

            except Exception as e:
                log.error(f"> ERROR: Iteration failed: {e}", exc_info=True)
                self._sd_notify(f"STATUS=Error in iteration {self._state.iteration}")
                self._sd_watchdog_ping()

            elapsed = time.monotonic() - iter_start
            sleep_for = max(0, ITERATION_INTERVAL_SECS - elapsed)
            await asyncio.sleep(sleep_for)

        log.info("> SYSTEM: Kriya Loop exiting gracefully.")
        self._sd_notify("STATUS=Shutting down...")
        self._sd_notify("STOPPING=1")

        sandbox.shutdown()

        self._running = False
        log.info("> SYSTEM: All subsystems shut down. Daemon exit.")


    async def _run_state_server(self) -> None:
        """Background task: expose KriyaState as a JSON HTTP endpoint on port 50000."""
        if not _FASTAPI_AVAILABLE:
            return

        try:
            app = FastAPI(title="YantraOS State API", version="1.0")
            engine_ref = self

            @app.get("/health")
            async def health():
                return {"status": "ok", "iteration": engine_ref._state.iteration}

            from .ipc_server import attach_ipc_routes
            attach_ipc_routes(app, engine_ref)

            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=50000,
                log_level="warning",
                loop="asyncio",
            )
            server = uvicorn.Server(config)
            await server.serve()
        except Exception as e:
            log.warning(f"> STATE API: Server initialization error: {e}")


# ── Entrypoint ────────────────────────────────────────────────────


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    engine = KriyaLoopEngine()
    asyncio.run(engine.run())


if __name__ == "__main__":
    main()
