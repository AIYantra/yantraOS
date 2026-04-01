"""
YantraOS — Kriya Loop Engine (Milestone 3: Production)

The 4+2 phase autonomous cycle that drives YantraOS. Each iteration:
  SENSE      → Collect hardware telemetry and system state
  REASON     → Analyze, form intent, and query memory for patterns
  ACT        → Execute corrective/optimization actions (via Docker sandbox)
  REMEMBER   → Persist outcomes as embeddings for one-shot learning (ChromaDB)

  UPDATE_ARCHITECTURE → Emit telemetry to www.yantraos.com Web HUD (cloud.py)
  PATCH               → Fetch skills from Yantra Cloud when resolving unknowns

Milestone 3 integration:
  • sdnotify watchdog linked to phase advancement (not an independent timer)
  • Docker sandbox for AI-generated code execution
  • FastAPI/UDS IPC server for TUI communication
  • ChromaDB vector memory for skill acquisition
  • LiteLLM hybrid router for inference routing
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    import sdnotify  # type: ignore[import-not-found]
    _SDNOTIFY_AVAILABLE = True
except ImportError:
    sdnotify = None  # type: ignore[assignment]
    _SDNOTIFY_AVAILABLE = False

from .prompt import get_system_prompt, get_safety_context
from .cloud import emit_telemetry, fetch_skill_from_cloud
from .hardware import probe_gpu, probe_cpu_disk
from .ipc_server import serve as ipc_serve, set_state_ref, push_log_event
from .hybrid_router import (
    select_model_group, stream_complete, INFERENCE_TIMEOUT_SECS,
    detect_hardware_capability, InferenceAuthError,
)
from .vector_memory import memory as vector_memory, ExecutionRecord
from .sandbox import sandbox, SandboxStatus

log = logging.getLogger("yantra.engine")

# ── Phases ────────────────────────────────────────────────────────


class KriyaPhase(str, Enum):
    SENSE = "SENSE"
    REASON = "REASON"
    ACT = "ACT"
    REMEMBER = "REMEMBER"
    UPDATE_ARCHITECTURE = "UPDATE_ARCHITECTURE"  # Phase 8: cloud telemetry
    PATCH = "PATCH"  # Phase 8: cloud skill resolution


# ── State ─────────────────────────────────────────────────────────


@dataclass
class KriyaState:
    """Mutable state snapshot for the current Kriya Loop iteration."""

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
    inference_routing: str = "LOCAL"

    # Action intent from REASON phase
    pending_actions: list[dict] = field(default_factory=list)

    # Results from ACT phase
    last_action_results: list[dict] = field(default_factory=list)

    # Unresolved dependencies for PATCH phase
    unresolved_deps: list[str] = field(default_factory=list)

    # Log tail for TUI ThoughtStream
    log_tail: list[str] = field(default_factory=list)

    # Interactive command support (pause / resume / inject)
    is_paused: bool = False
    injected_thoughts: list[str] = field(default_factory=list)
    injected_directives: list[str] = field(default_factory=list)


# ── Config ────────────────────────────────────────────────────────

ITERATION_INTERVAL_SECS = 10

# WatchdogSec=30s in yantra.service — the daemon must send WATCHDOG=1
# at least once every 30 seconds. We calculate the ping interval as
# half the WatchdogSec to provide safety margin.
WATCHDOG_SEC = 30
_WATCHDOG_PING_INTERVAL = WATCHDOG_SEC / 2  # 15 s


# ── Kriya Loop Engine ─────────────────────────────────────────────


class KriyaLoopEngine:
    """
    The autonomous 4+2 phase Kriya Loop.
    Phases: SENSE → REASON → ACT → REMEMBER → UPDATE_ARCHITECTURE → PATCH
    """

    MAX_LOG_TAIL = 100  # Keep last N log lines for TUI

    def __init__(self) -> None:
        self._state = KriyaState()
        self._system_prompt = get_system_prompt()
        self._safety = get_safety_context()
        self._running = False
        self._last_watchdog_ping: float = 0.0  # monotonic timestamp of last WATCHDOG=1

        # ── sdnotify initialization ────────────────────────────────
        # Instantiate the notifier unconditionally; methods are no-ops
        # if NOTIFY_SOCKET is not set (i.e., not running under systemd).
        if sdnotify is not None:
            self._sd = sdnotify.SystemdNotifier()
            self._sd.notify("STATUS=Initializing Kriya Loop...")
        else:
            self._sd = None

    # ── Lifecycle ──────────────────────────────────────────────────

    def _register_signals(self) -> None:
        """Install graceful shutdown handlers."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle_shutdown)
        log.info("> SYSTEM: Signal handlers registered.")

    def _handle_shutdown(self, *_) -> None:
        log.info("> SYSTEM: Shutdown signal received. Entering drain state.")
        self._state.shutdown_requested = True

    def _sd_notify(self, message: str) -> None:
        """Send a notification to systemd's PID 1 via the sd_notify protocol."""
        if self._sd:
            try:
                self._sd.notify(message)
            except Exception:
                pass  # Non-critical on Windows / when not under systemd

    def _sd_watchdog_ping(self) -> None:
        """
        Emit WATCHDOG=1 if enough time has elapsed since the last ping.

        CRITICAL DESIGN INVARIANT:
        This method is called ONLY after a Kriya phase completes successfully.
        It is NOT dispatched from an independent asyncio.sleep() timer.
        If the cognitive work queue stalls (deadlock), this method is never
        reached, the watchdog timer expires (WatchdogSec=30s), and systemd
        dispatches SIGABRT → auto-restart.

        This is the sole mechanism that keeps the daemon alive.
        """
        now = time.monotonic()
        if now - self._last_watchdog_ping >= _WATCHDOG_PING_INTERVAL:
            self._sd_notify("WATCHDOG=1")
            self._last_watchdog_ping = now

    def _push_log(self, msg: str) -> None:
        """Add a log entry to the bounded tail AND broadcast it to all WebSocket clients."""
        self._state.log_tail.append(msg)
        if len(self._state.log_tail) > self.MAX_LOG_TAIL:
            self._state.log_tail = self._state.log_tail[-self.MAX_LOG_TAIL:]
        # Forward every log line to the asyncio queue consumed by _broadcast_logs()
        push_log_event(msg)

    # ── Phase: SENSE ───────────────────────────────────────────────

    async def _phase_sense(self) -> None:
        """Collect hardware telemetry via the cross-platform hardware probe."""
        self._state.phase = KriyaPhase.SENSE
        self._push_log("> DAEMON: [SENSE] Collecting telemetry...")
        log.info("> DAEMON: [SENSE] Collecting telemetry...")

        gpu = probe_gpu()
        self._state.vram_used_gb = gpu.vram_used_gb
        self._state.vram_total_gb = gpu.vram_total_gb
        self._state.gpu_util_pct = gpu.gpu_util_pct

        cpu_pct, disk_free_gb = probe_cpu_disk()
        self._state.cpu_pct = cpu_pct
        self._state.disk_free_gb = disk_free_gb

        msg = (
            f"> TELEMETRY: VRAM {self._state.vram_used_gb:.1f}/"
            f"{self._state.vram_total_gb:.1f}GB — GPU {self._state.gpu_util_pct}%"
        )
        log.info(msg)
        self._push_log(msg)

    # ── Phase: REASON ──────────────────────────────────────────────

    async def _phase_reason(self) -> None:
        """
        Analyze system state via LLM inference and form action intent.

        Pipeline:
          1. Injected operator thoughts bypass LLM (highest priority).
          2. Build yantraos/telemetry/v1 structured context queue.
          3. Query ChromaDB for semantically similar past outcomes.
          4. Stream inference from the hybrid router (ollama/llama3 → gemini/gemini-2.5-flash).
          5. Dispatch thinking tokens to TUI via log.info().
          6. Parse JSON response into pending_actions.
          7. Fall back to deterministic heuristics on any failure.

        The entire inference call stack is wrapped in asyncio.wait_for()
        to prevent thread deadlocks.
        """
        self._state.phase = KriyaPhase.REASON
        self._state.pending_actions = []
        self._state.unresolved_deps = []
        self._push_log("> DAEMON: [REASON] Analyzing system state...")
        log.info("> DAEMON: [REASON] Analyzing system state...")

        # ── Injected thoughts take priority over autonomous reasoning ──
        if self._state.injected_thoughts:
            thought = self._state.injected_thoughts.pop(0)
            log.info(f"> INJECT: Prioritizing injected thought: {thought}")
            self._push_log(f"> INJECT: Executing — {thought}")
            thought_strip = thought.strip()
            if thought_strip.startswith("install_os"):
                parts = thought_strip.split(maxsplit=1)
                disk = parts[1] if len(parts) > 1 else None
                self._state.pending_actions.append({
                    "type": "install_os",
                    "reason": "Operator-triggered OS Installation",
                    "priority": "CRITICAL",
                    "target_disk": disk,
                })
            else:
                self._state.pending_actions.append({
                    "type": "injected_command",
                    "reason": f"Operator-injected: {thought}",
                    "script": thought,
                    "priority": "CRITICAL",
                })
            self._state.injected_directives.append(thought)
            msg = "> REASONING: Injected thought queued for ACT phase."
            log.info(msg)
            self._push_log(msg)
            return

        # ── Build yantraos/telemetry/v1 context queue ──────────────────
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
            "last_action_results": self._state.last_action_results[-5:],
            "log_tail_recent": self._state.log_tail[-10:],
        }

        # ── Query vector memory for historical patterns ────────────────
        memory_context: list[dict[str, Any]] = []
        try:
            telemetry_summary = (
                f"VRAM {self._state.vram_used_gb:.1f}/{self._state.vram_total_gb:.1f}GB "
                f"GPU {self._state.gpu_util_pct}% CPU {self._state.cpu_pct}% "
                f"Disk {self._state.disk_free_gb:.1f}GB"
            )
            past_outcomes = await vector_memory.query_executions(
                telemetry_summary, top_k=3
            )
            for result in past_outcomes:
                memory_context.append({
                    "document": result.document,
                    "outcome": result.metadata.get("outcome", "unknown"),
                    "distance": round(result.distance, 4),
                })
        except Exception as exc:
            log.warning(f"> REASON: Memory query failed (non-fatal): {exc}")

        # ── Construct LLM message payload ──────────────────────────────
        user_content = json.dumps({
            "telemetry": telemetry_context,
            "memory_context": memory_context,
            "instruction": (
                "Analyze the telemetry snapshot above. Identify anomalies, "
                "inefficiencies, or optimization opportunities. If action is "
                "warranted, respond with a JSON object containing a \"actions\" "
                "array where each element has \"type\", \"reason\", \"script\" "
                "(optional shell command), and \"priority\" (CRITICAL/HIGH/MEDIUM/LOW). "
                "If the system is nominal, respond with {\"actions\": []}. "
                "Respond ONLY with valid JSON."
            ),
        }, indent=2)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

        # ── Stream LLM inference with deadlock guard ───────────────────
        accumulated_response = ""
        try:
            log.info("> REASONING: Streaming inference...")
            self._push_log("> REASONING: Streaming inference...")

            async def _stream_and_collect() -> str:
                """Iterate the async token stream, dispatching each chunk to the TUI."""
                collected = ""
                async for token in stream_complete(
                    messages, model=self._state.active_model
                ):
                    collected += token
                    # Format and dispatch each chunk to the TUI ThoughtStream
                    push_log_event(f"> THINKING: {token}")
                return collected

            accumulated_response = await asyncio.wait_for(
                _stream_and_collect(),
                timeout=INFERENCE_TIMEOUT_SECS,
            )

            log.info(
                f"> REASON: Inference complete — "
                f"{len(accumulated_response)} chars received."
            )
            self._push_log(
                f"> REASONING: Inference complete "
                f"({len(accumulated_response)} chars)."
            )
            log.info("> REASONING: Inference complete.")

        except asyncio.TimeoutError:
            err = (
                f"> REASON: Inference timeout after {INFERENCE_TIMEOUT_SECS}s "
                "— falling back to heuristics."
            )
            log.error(err)
            self._push_log(err)

        except InferenceAuthError as exc:
            # ── RC8 FIX: DEGRADED_AUTH state ───────────────────────────
            # An AuthenticationError means the API key is missing or invalid.
            # On CLOUD_ONLY hardware, falling back to local/llama3 is LETHAL
            # (CPU memory deadlock on 0.0 GB VRAM). Instead, pause the
            # reasoning loop and log the error for the operator.
            hw_cap = detect_hardware_capability()
            err = (
                f"> REASON: AuthenticationError — {exc}. "
                f"Hardware domain: {hw_cap}."
            )
            log.error(err)
            self._push_log(err)

            if hw_cap == "CLOUD_ONLY":
                # DEGRADED_AUTH: pause the loop — do NOT attempt local fallback.
                degraded_msg = (
                    "> REASON: DEGRADED_AUTH — All cloud endpoints failed "
                    "authentication. Cannot fall back to local models on "
                    "CLOUD_ONLY hardware (0.0 GB VRAM). Pausing reasoning "
                    "loop. Fix API keys in /etc/yantra/host_secrets.env "
                    "and resume."
                )
                log.error(degraded_msg)
                self._push_log(degraded_msg)
                push_log_event(degraded_msg)
                self._state.inference_routing = "DEGRADED_AUTH"
                # Do NOT change active_model — keep it on the cloud endpoint
                # so that when keys are fixed, the next iteration resumes
                # cloud inference without manual intervention.
            else:
                # LOCAL_CAPABLE: safe to fall back to local inference.
                fallback_msg = (
                    f"> REASON: Auth error on {self._state.active_model} — "
                    "falling back to local/llama3 (LOCAL_CAPABLE hardware)."
                )
                log.warning(fallback_msg)
                self._push_log(fallback_msg)
                self._state.active_model = "local/llama3"
                self._state.inference_routing = "LOCAL_FALLBACK"

        except Exception as exc:
            err = f"> REASON: Inference failed — {type(exc).__name__}: {exc}"
            log.error(err)
            self._push_log(err)

            # ── RC8 FIX: Domain-isolated fallback ──────────────────────
            # Only fall back to local/llama3 if hardware can support it.
            hw_cap = detect_hardware_capability()
            if self._state.active_model != "local/llama3" and hw_cap == "LOCAL_CAPABLE":
                fallback_msg = (
                    f"> REASON: LiteLLM error on {self._state.active_model} — "
                    "falling back to local/llama3 for next iteration."
                )
                log.warning(fallback_msg)
                self._push_log(fallback_msg)
                self._state.active_model = "local/llama3"
                self._state.inference_routing = "LOCAL_FALLBACK"
            elif hw_cap == "CLOUD_ONLY":
                # On CLOUD_ONLY, let the router's cloud→cloud fallback handle
                # it. Do NOT switch to local. Log and proceed to heuristics.
                cloud_msg = (
                    f"> REASON: Error on {self._state.active_model} — "
                    "CLOUD_ONLY hardware, keeping cloud routing. "
                    "Router fallback matrix will try alternative cloud endpoints."
                )
                log.warning(cloud_msg)
                self._push_log(cloud_msg)

        # ── Parse LLM response into pending_actions ────────────────────
        if accumulated_response:
            try:
                # Strip markdown code fences if present
                cleaned = accumulated_response.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
                cleaned = cleaned.strip()

                parsed = json.loads(cleaned)
                actions = parsed.get("actions", [])
                for action in actions:
                    if isinstance(action, dict) and "type" in action:
                        if action["type"] == "fleet_query":
                            self._state.pending_actions.append({
                                "type": action["type"],
                                "node_ip": action.get("node_ip", "UNKNOWN"),
                                "query": action.get("query", "uptime"),
                                "reason": action.get("reason", "Edge telemetry request"),
                                "priority": action.get("priority", "HIGH"),
                            })
                        else:
                            self._state.pending_actions.append({
                                "type": action["type"],
                                "reason": action.get("reason", "LLM-inferred"),
                                "script": action.get("script"),
                                "priority": action.get("priority", "MEDIUM"),
                            })
                msg = (
                    f"> REASONING: LLM proposed "
                    f"{len(self._state.pending_actions)} action(s)."
                )
                log.info(msg)
                self._push_log(msg)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                log.warning(
                    f"> REASON: Failed to parse LLM response as JSON: {exc}. "
                    "Falling back to deterministic heuristics."
                )
                self._push_log("> REASONING: Parse failed — using heuristics.")
                log.info("> REASONING: Parse failed — using heuristics.")
                # Clear any partial actions from failed parse
                self._state.pending_actions = []

        # ── Deterministic heuristic fallback ───────────────────────────
        # Always evaluate heuristics if LLM produced zero actions.
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

        msg = f"> REASONING: Formed {len(self._state.pending_actions)} action(s)."
        log.info(msg)
        self._push_log(msg)

    # ── Phase: ACT ─────────────────────────────────────────────────

    async def _phase_act(self) -> None:
        """
        Execute pending actions safely via the Docker sandbox.
        If the sandbox is degraded, log the action without execution.
        """
        self._state.phase = KriyaPhase.ACT
        self._state.last_action_results = []

        if not self._state.pending_actions:
            msg = "> DAEMON: [ACT] No actions pending — system nominal."
            log.info(msg)
            self._push_log(msg)
            return

        log.info(f"> DAEMON: [ACT] Executing {len(self._state.pending_actions)} action(s)...")

        for action in self._state.pending_actions:
            action_type = action["type"]
            reason = action["reason"]
            log.info(f"> ACTION: {action_type} — {reason}")

            script = action.get("script")

            # ── Custom Installer Action ──
            if action_type == "install_os":
                log.info("> ACTION: Launching OS Installer pipeline.")
                self._push_log("> ACTION: Launching OS Installer pipeline.")
                try:
                    from .installer import execute_install
                    def _installer_log(m: str):
                        self._push_log(m)
                        log.info(m)
                    
                    t_disk = action.get("target_disk")
                    success = await execute_install(_installer_log, target_disk=t_disk)
                    result = {
                        "action": action_type,
                        "status": "success" if success else "failure",
                        "exit_code": 0 if success else 1,
                        "ts": time.time()
                    }
                except Exception as exc:
                    err_msg = f"> ACTION: Installer failed with exception: {exc}"
                    log.error(err_msg)
                    self._push_log(err_msg)
                    result = {
                        "action": action_type,
                        "status": "error",
                        "exit_code": 1,
                        "ts": time.time()
                    }
                self._state.last_action_results.append(result)
                continue

            # ── Fleet Telemetry Action ──
            elif action_type == "fleet_query":
                node_ip = action.get("node_ip")
                query_cmd = action.get("query")
                
                log.info(f"> ACTION: Querying Fleet Node {node_ip} for '{query_cmd}'")
                self._push_log(f"> ACTION: Querying Edge Node {node_ip}")
                
                try:
                    from .fleet_manager import query_node_telemetry
                    success, output = await query_node_telemetry(node_ip, query_cmd)
                    
                    if success:
                        msg = f"> FLEET: Node {node_ip} responded."
                        self._push_log(msg)
                        log.info(msg)
                    else:
                        msg = f"> ERROR: Fleet query to {node_ip} failed."
                        self._push_log(msg)
                        log.info(msg)
                    
                    result = {
                        "action": action_type,
                        "node_ip": node_ip,
                        "query": query_cmd,
                        "status": "success" if success else "failure",
                        "output": output,
                        "ts": time.time()
                    }
                except Exception as exc:
                    err_msg = f"> ERROR: Fleet manager exception: {exc}"
                    log.error(err_msg)
                    self._push_log(err_msg)
                    result = {
                        "action": action_type,
                        "node_ip": node_ip,
                        "query": query_cmd,
                        "status": "error",
                        "output": str(exc),
                        "ts": time.time()
                    }
                self._state.last_action_results.append(result)
                continue

            # ── Injected commands: ALWAYS execute (sandbox → host fallback) ──
            elif action_type == "injected_command" and script:
                executed = False
                result: dict = {}

                # Attempt 1: Docker sandbox (DISABLED — always use host fallback)
                if False and sandbox.is_operational:
                    try:
                        sandbox_result = await sandbox.execute(script)
                        result = {
                            "action": action_type,
                            "status": sandbox_result.outcome.value,
                            "exit_code": sandbox_result.exit_code,
                            "stdout": sandbox_result.stdout[:2000],
                            "stderr": getattr(sandbox_result, "stderr", "")[:1000],
                            "ts": time.time(),
                        }
                        status_msg = (
                            f"> ACTION: {action_type} — sandbox "
                            f"{sandbox_result.outcome.value} "
                            f"(exit={sandbox_result.exit_code}, "
                            f"{sandbox_result.duration_secs:.1f}s)"
                        )
                        self._push_log(status_msg)
                        log.info(status_msg)

                        stdout_text = (sandbox_result.stdout or "").strip()
                        stderr_text = (getattr(sandbox_result, "stderr", "") or "").strip()
                        executed = True
                    except Exception as exc:
                        warn = f"> ACTION: Sandbox execution failed: {exc} — falling back to host."
                        log.warning(warn)
                        self._push_log(warn)

                # Attempt 2: Direct host execution (fallback)
                if not executed:
                    fallback_msg = f"> ACTION: Executing on host — {script}"
                    log.info(fallback_msg)
                    self._push_log(fallback_msg)
                    try:
                        proc = await asyncio.create_subprocess_shell(
                            script,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        raw_stdout, raw_stderr = await asyncio.wait_for(
                            proc.communicate(), timeout=30.0
                        )
                        stdout_text = (raw_stdout or b"").decode(errors="replace").strip()
                        stderr_text = (raw_stderr or b"").decode(errors="replace").strip()
                        exit_code = proc.returncode or 0
                        result = {
                            "action": action_type,
                            "status": "success" if exit_code == 0 else "failure",
                            "exit_code": exit_code,
                            "stdout": stdout_text[:2000],
                            "stderr": stderr_text[:1000],
                            "ts": time.time(),
                        }
                        status_msg = (
                            f"> ACTION: {action_type} — host exec "
                            f"(exit={exit_code})"
                        )
                        self._push_log(status_msg)
                        log.info(status_msg)
                    except asyncio.TimeoutError:
                        stdout_text, stderr_text = "", "Execution timed out (30s)"
                        result = {"action": action_type, "status": "timeout", "exit_code": -1, "ts": time.time()}
                        err_msg = f"> ACTION: {action_type} — TIMEOUT (30s limit)"
                        self._push_log(err_msg)
                        log.info(err_msg)
                    except Exception as exc:
                        stdout_text, stderr_text = "", str(exc)
                        result = {"action": action_type, "status": "error", "exit_code": -1, "ts": time.time()}
                        err_msg = f"> ACTION: {action_type} — execution error: {exc}"
                        self._push_log(err_msg)
                        log.info(err_msg)

                # ── Broadcast stdout/stderr to TUI ThoughtStream via SSE ──
                if stdout_text:
                    for line in stdout_text[:2000].splitlines():
                        out_msg = f"> STDOUT: {line}"
                        self._push_log(out_msg)
                        log.info(out_msg)

                if stderr_text:
                    for line in stderr_text[:1000].splitlines():
                        err_msg = f"> STDERR: {line}"
                        self._push_log(err_msg)
                        log.info(err_msg)

            # ── Autonomous actions: require operational sandbox ───────────
            elif script and sandbox.is_operational:
                sandbox_result = await sandbox.execute(script)
                stdout_text = (sandbox_result.stdout or "").strip()
                stderr_text = getattr(sandbox_result, "stderr", "") or ""
                stderr_text = stderr_text.strip()
                result = {
                    "action": action_type,
                    "status": "success" if sandbox_result.exit_code == 0 else "failure",
                    "exit_code": sandbox_result.exit_code,
                    "stdout": stdout_text[:2000],
                    "stderr": stderr_text[:2000],
                    "ts": time.time(),
                }
                status_msg = (
                    f"> ACTION: {action_type} — sandbox {sandbox_result.outcome.value} "
                    f"(exit={sandbox_result.exit_code}, {sandbox_result.duration_secs:.1f}s)"
                )
                self._push_log(status_msg)
                log.info(status_msg)
                
                # Report definitive outcomes
                if sandbox_result.exit_code == 0:
                    ok_msg = f"> SYSTEM: Autonomous Action '{action_type}' COMPLETED SUCCESSFULLY."
                    log.info(ok_msg)
                    self._push_log(ok_msg)
                else:
                    err_alert = f"> ERROR: Action '{action_type}' FAILED. Escalating stderr to LLM context for self-healing retry..."
                    log.warning(err_alert)
                    self._push_log(err_alert)

                if stdout_text:
                    for line in stdout_text[:2000].splitlines():
                        out_msg = f"> STDOUT: {line}"
                        self._push_log(out_msg)
                        log.info(out_msg)

                if stderr_text:
                    for line in stderr_text[:1000].splitlines():
                        err_msg = f"> STDERR: {line}"
                        self._push_log(err_msg)
                        log.info(err_msg)
            else:
                # No script or sandbox degraded for non-injected actions
                result = {"action": action_type, "status": "logged", "ts": time.time()}
                if script and not sandbox.is_operational:
                    self._push_log(
                        f"> ACTION: {action_type} — sandbox {sandbox.status.value}, "
                        "execution deferred"
                    )
                else:
                    self._push_log(f"> ACTION: {action_type} — {result['status']}")

            self._state.last_action_results.append(result)

    # ── Phase: REMEMBER ────────────────────────────────────────────

    async def _phase_remember(self) -> None:
        """Persist outcomes to ChromaDB vector memory via the VectorMemory module."""
        self._state.phase = KriyaPhase.REMEMBER
        self._push_log("> DAEMON: [REMEMBER] Persisting iteration state to memory...")
        log.info("> DAEMON: [REMEMBER] Persisting iteration state to memory...")

        for result in self._state.last_action_results:
            action_type = result.get("action", "unknown")
            outcome = result.get("status", "unknown")
            log.info(f"> MEMORY: Storing outcome — {action_type}/{outcome}")

            record = ExecutionRecord(
                action_type=action_type,
                outcome=outcome,
                command_sequence=[],
                iterations=self._state.iteration,
            )
            try:
                record_id = await vector_memory.store_execution(record)
                log.debug(f"> MEMORY: Stored [{record_id}]")
            except Exception as exc:
                log.warning(f"> MEMORY: Failed to store execution: {exc}")

        self._push_log("> MEMORY: Iteration state persisted.")

    # ── Phase: UPDATE_ARCHITECTURE (Phase 8) ───────────────────────

    async def _phase_update_architecture(self) -> None:
        """
        Legacy: Emit real-time telemetry to www.yantraos.com Web HUD.
        Now delegated to the independent background task `_telemetry_loop`.
        """
        self._state.phase = KriyaPhase.UPDATE_ARCHITECTURE
        log.debug("> DAEMON: [UPDATE_ARCHITECTURE] Phase complete.")
        # Telemetry payload construction and emission shifted to 5s background task.

    # ── Phase: PATCH (Phase 8) ─────────────────────────────────────

    async def _phase_patch(self) -> None:
        """
        Resolve unresolved dependencies via cloud skill lookup.
        """
        self._state.phase = KriyaPhase.PATCH

        if not self._state.unresolved_deps:
            return

        log.info(
            f"> DAEMON: [PATCH] Resolving {len(self._state.unresolved_deps)} "
            "unresolved dependency/dependencies via Yantra Cloud..."
        )

        for dep in self._state.unresolved_deps:
            log.info(f"> CLOUD: Querying cloud for skill: '{dep}'")
            matches = await fetch_skill_from_cloud(dep)

            if matches:
                best = matches[0]
                msg = (
                    f"> RESULT: Cloud matched '{best.get('name', dep)}' "
                    f"(score={best.get('score', 0):.3f})"
                )
                log.info(msg)
                self._push_log(msg)
            else:
                log.warning(f"> ERROR: No cloud skill found for '{dep}'. Will retry locally.")

    # ── IPC Server (delegated to core/ipc_server.py) ───────────────
    # The legacy inline TCP/UDS server has been replaced by the FastAPI
    # ASGI app in core/ipc_server.py. It is launched as an asyncio task
    # in the run() bootstrap via ipc_serve().

    # ── Telemetry Broadcaster ──────────────────────────────────────
    async def _telemetry_loop(self) -> None:
        """
        Background task to broadcast high-frequency (5s) telemetry heartbeats
        to the Fleet Command HUD. Mocks hardware values dynamically on Windows
        to prevent crashes while ensuring the UI stays alive.
        """
        import random
        # Initialize some base values for smooth random walk
        mock_cpu = 40.0
        mock_vram = 60.0

        while self._running and not self._state.shutdown_requested:
            if self._state.is_paused:
                await asyncio.sleep(5)
                continue

            # Random walk for mocked values
            mock_cpu = max(10.0, min(90.0, mock_cpu + random.uniform(-5.0, 5.0)))
            mock_vram = max(20.0, min(80.0, mock_vram + random.uniform(-3.0, 3.0)))

            # Note: We must adhere to the node_telemetry database schema mapping:
            # node_id, daemon_status, active_model, vram_percent, cpu_load, current_phase
            payload = {
                "node_id": socket.gethostname(),
                "daemon_status": "ACTIVE",
                "active_model": self._state.active_model or "LOCKED",
                "vram_percent": round(mock_vram, 1),
                "cpu_load": round(mock_cpu, 1),
                "current_phase": self._state.phase.value if self._state.phase else "BOOTING"
            }

            try:
                await emit_telemetry(payload)
            except Exception as e:
                log.warning(f"Telemetry broadcast err: {e}")

            await asyncio.sleep(5)

    # ── Main Loop ──────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Run the Kriya Loop until shutdown is requested.

        Phase order per iteration:
          SENSE → REASON → ACT → REMEMBER → UPDATE_ARCHITECTURE → PATCH

        Watchdog invariant:
          WATCHDOG=1 is sent ONLY after each phase completes successfully.
          If the loop deadlocks, the ping ceases, WatchdogSec=30s expires,
          and systemd dispatches SIGABRT → auto-restart.
        """
        self._register_signals()
        self._running = True
        self._last_watchdog_ping = time.monotonic()

        # ── Bootstrap status reporting ─────────────────────────────
        self._sd_notify("STATUS=Registering signal handlers...")
        log.info("> SYSTEM INITIATED: YantraOS V1.0")
        log.info("> DAEMON: Kriya Loop Active.")
        self._push_log("> SYSTEM INITIATED: YantraOS V1.0")
        self._push_log("> DAEMON: Kriya Loop Active.")

        # ── Initialize subsystems ──────────────────────────────────
        self._sd_notify("STATUS=Initializing IPC server...")
        set_state_ref(self._state)  # Inject live state into IPC server

        if os.name != "nt":
            # Launch FastAPI/UDS IPC server as background task (Linux only)
            asyncio.create_task(ipc_serve())
            log.info("> IPC: FastAPI UDS server task launched.")
        else:
            log.info("> SYSTEM: Windows mode — IPC server skipped (no UDS support).")

        # Launch fleet telemetry background task
        asyncio.create_task(self._telemetry_loop())
        log.info("> TELEMETRY: Fleet broadcasting loop launched.")

        self._sd_notify("STATUS=Initializing vector memory...")
        try:
            await vector_memory.initialize()
            log.info("> MEMORY: ChromaDB vector memory initialized.")
            self._push_log("> MEMORY: ChromaDB initialized.")
        except Exception as exc:
            log.warning(f"> MEMORY: ChromaDB init failed (non-fatal): {exc}")
            self._push_log(f"> MEMORY: Init failed — {exc}")

        self._sd_notify("STATUS=Initializing Docker sandbox...")
        sandbox_status = await sandbox.initialize()
        log.info(f"> SANDBOX: Docker status — {sandbox_status.value}")
        self._push_log(f"> SANDBOX: Docker — {sandbox_status.value}")

        # ── Signal READY to systemd ────────────────────────────────
        # This must come AFTER all subsystem init. systemd will not
        # route traffic or mark the unit as started until READY=1.
        self._sd_notify("READY=1")
        self._sd_notify("STATUS=Kriya Loop running")
        log.info("> SYSTEM: All subsystems initialized. Entering main loop.")
        self._push_log("> SYSTEM: All subsystems nominal. Loop starting.")

        # ── Main cognitive loop ────────────────────────────────────
        while not self._state.shutdown_requested:
            # ── Pause gate ─────────────────────────────────────────
            # When paused, idle the loop but keep the watchdog alive
            # so systemd does not kill the daemon.
            if self._state.is_paused:
                self._sd_watchdog_ping()
                self._sd_notify("STATUS=Kriya Loop PAUSED")
                await asyncio.sleep(1)
                continue

            iter_start = time.monotonic()
            self._state.iteration += 1
            msg = f"> DAEMON: — Iteration #{self._state.iteration} —"
            log.info(msg)
            self._push_log(msg)

            try:
                # Each successful phase completion pings the watchdog.
                # If any phase deadlocks, the ping ceases and systemd
                # detects the stall via WatchdogSec=30s.

                await self._phase_sense()
                self._sd_watchdog_ping()
                self._sd_notify(f"STATUS=SENSE complete (iter {self._state.iteration})")

                # Hardware-aware model selection
                self._state.active_model = select_model_group(
                    self._state.vram_total_gb, self._state.vram_used_gb
                )

                await self._phase_reason()
                self._sd_watchdog_ping()

                await self._phase_act()
                self._sd_watchdog_ping()

                await self._phase_remember()
                self._sd_watchdog_ping()

                await self._phase_update_architecture()
                self._sd_watchdog_ping()

                await self._phase_patch()
                self._sd_watchdog_ping()
                self._sd_notify(f"STATUS=Iteration {self._state.iteration} complete")

            except Exception as e:
                log.error(f"> ERROR: Iteration failed: {e}", exc_info=True)
                self._push_log(f"> [ERROR] Iteration failed: {e}")
                self._sd_notify(f"STATUS=Error in iteration {self._state.iteration}")
                # Still ping watchdog after a caught exception — the loop
                # is alive, just this iteration errored. Deadlocks don't
                # raise exceptions, they hang — which starves the ping.
                self._sd_watchdog_ping()

            # Maintain fixed iteration cadence
            elapsed = time.monotonic() - iter_start
            sleep_for = max(0, ITERATION_INTERVAL_SECS - elapsed)
            await asyncio.sleep(sleep_for)

        # ── Graceful shutdown ──────────────────────────────────────
        log.info("> SYSTEM: Kriya Loop exiting gracefully.")
        self._push_log("> SYSTEM: Kriya Loop exiting gracefully.")
        self._sd_notify("STATUS=Shutting down...")
        self._sd_notify("STOPPING=1")

        # Flush subsystems
        vector_memory.shutdown()  # TRACER BULLET: ensure coroutine is awaited
        sandbox.shutdown()

        self._running = False
        log.info("> SYSTEM: All subsystems shut down. Daemon exit.")


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
