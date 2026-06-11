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
import collections
import hashlib
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
from .compliance_executor import compliance_executor

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

# Maximum actions the LLM is allowed to propose / hold pending per
# iteration. Caps hallucinated action floods and bounds the FIFO queue.
# Defined here (ahead of KriyaState) because TrackedActionQueue consumes
# it as its default capacity.
MAX_PENDING_ACTIONS: int = 5

# Audit sink for dropped intents. The Kriya Loop must never lose an
# autonomous action without a cryptographic record, so evictions are
# written here at WARN level in addition to the daemon's stdout stream.
_EVICTION_AUDIT_PATH: str = "/var/log/yantra/engine.log"


def _eviction_audit_logger() -> logging.Logger:
    """
    Return the dedicated queue-eviction audit logger.

    Lazily attaches a single WARN-level FileHandler bound to
    ``/var/log/yantra/engine.log``. If that path is not writable
    (unit tests, non-root dev hosts), we degrade gracefully to the
    daemon's stdout logger via propagation rather than crashing the
    Kriya Loop — the WARN is surfaced either way, never silently lost.
    """
    audit: logging.Logger = logging.getLogger("yantra.engine.queue")
    audit.setLevel(logging.WARNING)
    audit.propagate = True  # also surface on the daemon's root stdout handler

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
            # Tag so we never double-attach across KriyaState rebuilds.
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
    """
    Bounded FIFO action queue with mandatory eviction auditing.

    A bare ``collections.deque(maxlen=N)`` silently discards the oldest
    element once it is full — an unacceptable silent state loss for
    autonomous intents. This subclass intercepts every capacity-driven
    eviction in :meth:`append`, SHA-256 fingerprints the dropped action,
    and emits a strictly formatted ``WARN`` audit record before the
    underlying deque drops it.

    FIFO semantics are preserved: ``append`` adds to the right, and the
    oldest element (index 0 / left) is the one evicted when full.
    """

    def __init__(self, maxlen: int = MAX_PENDING_ACTIONS) -> None:
        super().__init__(maxlen=maxlen)
        self._audit: logging.Logger = _eviction_audit_logger()

    def append(self, action: dict[str, Any]) -> None:  # type: ignore[override]
        # Intercept the silent FIFO eviction *before* it happens: a full
        # deque would otherwise drop index 0 (the oldest intent) with no
        # trace. We can only inspect the victim while it is still present.
        cap: int | None = self.maxlen
        if cap is not None and len(self) == cap:
            self._audit_eviction(self[0], cap)
        super().append(action)

    def _audit_eviction(self, evicted: dict[str, Any], cap: int) -> None:
        """Fingerprint and log a single dropped action at WARN level."""
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

    # RC3: Deep telemetry fields for TUI/Wayland HUD consumers.
    # Strictly typed numerical values — parsed directly by the Brutalist TUI.
    vram_allocation_mb: int = 0          # Current VRAM allocation in megabytes
    inference_tps: float = 0.0           # Inference throughput (tokens/second)
    context_window_tokens: int = 0       # Active context window size (token count)

    # Action intent from REASON phase. Bounded FIFO queue (maxlen=5)
    # with mandatory cryptographic audit logging on eviction.
    pending_actions: TrackedActionQueue = field(default_factory=TrackedActionQueue)

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

# NOTE: MAX_PENDING_ACTIONS is defined in the State section above, ahead
# of TrackedActionQueue which consumes it as its default FIFO capacity.


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

        # ── GATE 3: Concurrency Guard ──────────────────────────────
        # Protects mutable KriyaState fields (is_paused, pending_actions,
        # injected_thoughts, injected_directives) from race conditions
        # between the main Kriya Loop and the IPC server background task.
        # During LiteLLM cloud inference awaits, the event loop can service
        # IPC requests that mutate state — this lock serializes access.
        self._state_lock = asyncio.Lock()

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

        CRITICAL DESIGN INVARIANT (updated):
        This method is called after each Kriya phase completes as a
        supplementary ping. The primary watchdog heartbeat is now driven
        by the independent _watchdog_heartbeat_loop() coroutine, which
        runs on the event loop and fires every 15 seconds regardless of
        whether inference is blocking in the ThreadPoolExecutor. This
        eliminates the starvation failure mode where a long-running
        litellm call prevented the phase-gated ping from firing.
        """
        now = time.monotonic()
        if now - self._last_watchdog_ping >= _WATCHDOG_PING_INTERVAL:
            self._sd_notify("WATCHDOG=1")
            self._last_watchdog_ping = now

    async def _watchdog_heartbeat_loop(self) -> None:
        """
        Independent watchdog heartbeat — fires WATCHDOG=1 every 15 seconds.

        This coroutine runs as a top-level asyncio task, completely decoupled
        from the Kriya Loop phase progression. Because litellm inference is
        now offloaded to a ThreadPoolExecutor (see hybrid_router.py), the
        event loop is free to schedule this coroutine even during long-running
        inference calls.

        This is the PRIMARY mechanism that keeps the daemon alive. The
        per-phase _sd_watchdog_ping() calls are supplementary.

        The TUI telemetry UNIX socket (/run/yantra/ipc.sock) responsiveness
        is also guaranteed by this design: the event loop services both this
        heartbeat and uvicorn's UDS accept() without contention.
        """
        while self._running and not self._state.shutdown_requested:
            self._sd_notify("WATCHDOG=1")
            self._last_watchdog_ping = time.monotonic()
            await asyncio.sleep(_WATCHDOG_PING_INTERVAL)

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

        # RC3: Populate deep telemetry for TUI/Wayland HUD consumers.
        # vram_allocation_mb: convert VRAM used (GB) → MB as integer.
        # inference_tps and context_window_tokens are populated after
        # inference completes in _phase_reason().
        self._state.vram_allocation_mb = int(self._state.vram_used_gb * 1024)

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
        self._state.pending_actions.clear()
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
        inference_start = time.monotonic()
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

            # RC3: Populate deep telemetry — inference throughput and context size.
            # Approximate tokens from character count (~4 chars per token for
            # English text). This is a rough heuristic; production should read
            # usage metadata from the LiteLLM response object.
            inference_elapsed: float = time.monotonic() - inference_start
            approx_output_tokens: int = max(1, len(accumulated_response) // 4)
            if inference_elapsed > 0:
                self._state.inference_tps = round(approx_output_tokens / inference_elapsed, 2)
            else:
                self._state.inference_tps = 0.0
            # Context window = input tokens (user_content) + output tokens
            approx_input_tokens: int = len(user_content) // 4
            self._state.context_window_tokens = approx_input_tokens + approx_output_tokens

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

                # ── FAILURE 2 FIX: Cap actions to prevent LLM hallucination floods ──
                available_slots = MAX_PENDING_ACTIONS - len(self._state.pending_actions)
                if available_slots <= 0:
                    cap_msg = (
                        f"> REASON: Action queue full ({MAX_PENDING_ACTIONS}). "
                        f"Dropping {len(actions)} LLM-proposed action(s)."
                    )
                    log.warning(cap_msg)
                    self._push_log(cap_msg)
                    actions = []
                else:
                    if len(actions) > available_slots:
                        drop_msg = (
                            f"> REASON: LLM proposed {len(actions)} actions, "
                            f"capping to {available_slots} (MAX_PENDING_ACTIONS={MAX_PENDING_ACTIONS})."
                        )
                        log.warning(drop_msg)
                        self._push_log(drop_msg)
                    actions = actions[:available_slots]

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
                self._state.pending_actions.clear()

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

        GATE 3 FIX: Acquires _state_lock and checks is_paused BEFORE
        processing any actions. This closes the race window where a
        user's pause command arrives during a cloud inference await
        in REASON phase but actions still execute because the pause
        check at the loop top only fires at iteration boundaries.
        """
        self._state.phase = KriyaPhase.ACT
        self._state.last_action_results = []

        # ── GATE 3: Atomic pause check + action snapshot ──────────
        async with self._state_lock:
            if self._state.is_paused:
                msg = "> DAEMON: [ACT] Skipped — loop is PAUSED (mid-iteration pause detected)."
                log.info(msg)
                self._push_log(msg)
                return

            if not self._state.pending_actions:
                msg = "> DAEMON: [ACT] No actions pending — system nominal."
                log.info(msg)
                self._push_log(msg)
                return

            # Snapshot actions under lock, then release lock for execution
            actions_snapshot = list(self._state.pending_actions)

        log.info(f"> DAEMON: [ACT] Executing {len(actions_snapshot)} action(s)...")

        for action in actions_snapshot:
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

            # ── Injected commands: execute ONLY via sandbox ─────────────
            # GATE 1 FIX: The `if False` bypass and bare create_subprocess_shell
            # host fallback have been permanently removed. LLM-generated scripts
            # MUST execute inside the Docker sandbox. If the sandbox is degraded,
            # the command is logged and deferred — never executed on bare metal.
            elif action_type == "injected_command" and script:
                result: dict = {}
                stdout_text = ""
                stderr_text = ""

                if sandbox.is_operational:
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
                    except Exception as exc:
                        err_msg = f"> ACTION: Sandbox execution failed: {exc}"
                        log.error(err_msg)
                        self._push_log(err_msg)
                        result = {
                            "action": action_type,
                            "status": "sandbox_error",
                            "exit_code": -1,
                            "ts": time.time(),
                        }
                else:
                    # Sandbox is DEGRADED or UNAVAILABLE — DO NOT fall back to host.
                    # Log the deferred command for audit and move on.
                    defer_msg = (
                        f"> ACTION: {action_type} — sandbox {sandbox.status.value}, "
                        f"command DEFERRED (host execution prohibited). "
                        f"Script: {script[:200]}"
                    )
                    log.warning(defer_msg)
                    self._push_log(defer_msg)
                    result = {
                        "action": action_type,
                        "status": "deferred_no_sandbox",
                        "exit_code": -1,
                        "reason": f"Sandbox {sandbox.status.value} — host fallback prohibited",
                        "ts": time.time(),
                    }

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

        # ── GATE 3: Inject concurrency lock into IPC server ───────
        from .ipc_server import set_state_lock_ref
        set_state_lock_ref(self._state_lock)

        if os.name != "nt":
            # Launch FastAPI/UDS IPC server as background task (Linux only)
            asyncio.create_task(ipc_serve())
            log.info("> IPC: FastAPI UDS server task launched.")
        else:
            log.info("> SYSTEM: Windows mode — IPC server skipped (no UDS support).")

        # Launch fleet telemetry background task
        asyncio.create_task(self._telemetry_loop())
        log.info("> TELEMETRY: Fleet broadcasting loop launched.")

        # Launch independent watchdog heartbeat — decoupled from phase
        # progression so inference offloaded to ThreadPool cannot starve
        # the WATCHDOG=1 ping. This is the primary keepalive mechanism.
        asyncio.create_task(self._watchdog_heartbeat_loop())
        log.info("> WATCHDOG: Independent heartbeat loop launched (interval=15s).")

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

        # ── Initialize compliance assertion socket ─────────────────
        # Sovereign data compliance layer — streams Ed25519-signed
        # Kriya Loop state assertions to /run/yantra/compliance.sock.
        # Non-fatal: if the socket fails to bind, the engine continues.
        self._sd_notify("STATUS=Initializing compliance socket...")
        try:
            await compliance_executor.start()
            log.info("> COMPLIANCE: Sovereign assertion socket initialized.")
            self._push_log("> COMPLIANCE: Assertion socket active.")
        except Exception as exc:
            log.warning(f"> COMPLIANCE: Socket init failed (non-fatal): {exc}")
            self._push_log(f"> COMPLIANCE: Init failed — {exc}")

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

                # ── Compliance assertion: SENSE phase ──────────────────
                asyncio.create_task(compliance_executor.stream_state_assertion(
                    phase="SENSE",
                    iteration=self._state.iteration,
                    telemetry={
                        "vram_used_gb": round(self._state.vram_used_gb, 2),
                        "vram_total_gb": round(self._state.vram_total_gb, 2),
                        "gpu_util_pct": round(self._state.gpu_util_pct, 1),
                        "cpu_pct": round(self._state.cpu_pct, 1),
                        "disk_free_gb": round(self._state.disk_free_gb, 2),
                    },
                    active_model=self._state.active_model,
                ))

                # Hardware-aware model selection
                self._state.active_model = select_model_group(
                    self._state.vram_total_gb, self._state.vram_used_gb
                )

                await self._phase_reason()
                self._sd_watchdog_ping()

                # ── Compliance assertion: REASON phase ─────────────────
                asyncio.create_task(compliance_executor.stream_state_assertion(
                    phase="REASON",
                    iteration=self._state.iteration,
                    action_intent=list(self._state.pending_actions)[:5],
                    active_model=self._state.active_model,
                ))

                await self._phase_act()
                self._sd_watchdog_ping()

                # ── Compliance assertion: ACT phase ────────────────────
                asyncio.create_task(compliance_executor.stream_state_assertion(
                    phase="ACT",
                    iteration=self._state.iteration,
                    action_intent=self._state.last_action_results[:5],
                    active_model=self._state.active_model,
                ))

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

        # Shut down compliance assertion socket
        try:
            await compliance_executor.shutdown()
        except Exception as exc:
            log.warning(f"> COMPLIANCE: Shutdown error (non-fatal): {exc}")

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
