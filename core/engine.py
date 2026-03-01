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
    import sdnotify
    _SDNOTIFY_AVAILABLE = True
except ImportError:
    _SDNOTIFY_AVAILABLE = False

from .prompt import get_system_prompt, get_safety_context
from .cloud import emit_telemetry, fetch_skill_from_cloud
from .hardware import probe_gpu, probe_cpu_disk
from .ipc_server import serve as ipc_serve, set_state_ref, push_log_event
from .hybrid_router import select_model_group
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


# ── Config ────────────────────────────────────────────────────────

ITERATION_INTERVAL_SECS = 10

# WatchdogSec=15 in yantra.service — the daemon must send WATCHDOG=1
# at least once every 15 seconds. We calculate the ping interval as
# half the WatchdogSec to provide safety margin.
WATCHDOG_SEC = 15
_WATCHDOG_PING_INTERVAL = WATCHDOG_SEC / 2  # 7.5 s


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
        if _SDNOTIFY_AVAILABLE:
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
        reached, the watchdog timer expires (WatchdogSec=15), and systemd
        dispatches SIGABRT → auto-restart.

        This is the sole mechanism that keeps the daemon alive.
        """
        now = time.monotonic()
        if now - self._last_watchdog_ping >= _WATCHDOG_PING_INTERVAL:
            self._sd_notify("WATCHDOG=1")
            self._last_watchdog_ping = now

    def _push_log(self, msg: str) -> None:
        """Add a log entry and keep tail bounded."""
        self._state.log_tail.append(msg)
        if len(self._state.log_tail) > self.MAX_LOG_TAIL:
            self._state.log_tail = self._state.log_tail[-self.MAX_LOG_TAIL:]

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
        """Analyze state and form action intent."""
        self._state.phase = KriyaPhase.REASON
        self._state.pending_actions = []
        self._state.unresolved_deps = []
        self._push_log("> DAEMON: [REASON] Analyzing system state...")
        log.info("> DAEMON: [REASON] Analyzing system state...")

        # Example heuristics (extend with LLM reasoning)
        if self._state.disk_free_gb < 5:
            self._state.pending_actions.append({
                "type": "cleanup",
                "reason": f"Low disk space: {self._state.disk_free_gb:.1f}GB free",
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

            # If the action has a script payload and sandbox is healthy, execute it
            script = action.get("script")
            if script and sandbox.is_operational:
                sandbox_result = await sandbox.execute(script)
                result = {
                    "action": action_type,
                    "status": sandbox_result.outcome.value,
                    "exit_code": sandbox_result.exit_code,
                    "stdout": sandbox_result.stdout[:500],  # Truncate for log
                    "ts": time.time(),
                }
                self._push_log(
                    f"> ACTION: {action_type} — sandbox {sandbox_result.outcome.value} "
                    f"(exit={sandbox_result.exit_code}, {sandbox_result.duration_secs:.1f}s)"
                )
            else:
                # No script or sandbox degraded — log only
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
        Emit real-time telemetry to www.yantraos.com Web HUD.
        Non-blocking: failures are logged but never stall the loop.
        """
        self._state.phase = KriyaPhase.UPDATE_ARCHITECTURE
        log.debug("> DAEMON: [UPDATE_ARCHITECTURE] Emitting telemetry to www.yantraos.com...")

        payload: dict[str, Any] = {
            "daemon_status": "ACTIVE",
            "vram_usage": {
                "used_gb": round(self._state.vram_used_gb, 2),
                "total_gb": round(self._state.vram_total_gb, 2),
                "util_pct": round(
                    (self._state.vram_used_gb / max(self._state.vram_total_gb, 1)) * 100, 1
                ),
            },
            "current_cycle": {
                "phase": self._state.phase.value,
                "iteration": self._state.iteration,
            },
            "cpu_pct": round(self._state.cpu_pct, 1),
            "disk_free_gb": round(self._state.disk_free_gb, 2),
            "active_model": self._state.active_model,
            "inference_routing": self._state.inference_routing,
            "timestamp": time.time(),
            "hostname": socket.gethostname(),
        }

        ok = await emit_telemetry(payload)
        if ok:
            self._push_log("> TELEMETRY: Cloud emission successful.")
        else:
            self._push_log("> TELEMETRY: Cloud emission failed (non-critical).")

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

    # ── Main Loop ──────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Run the Kriya Loop until shutdown is requested.

        Phase order per iteration:
          SENSE → REASON → ACT → REMEMBER → UPDATE_ARCHITECTURE → PATCH

        Watchdog invariant:
          WATCHDOG=1 is sent ONLY after each phase completes successfully.
          If the loop deadlocks, the ping ceases, WatchdogSec=15 expires,
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
            iter_start = time.monotonic()
            self._state.iteration += 1
            msg = f"> DAEMON: — Iteration #{self._state.iteration} —"
            log.info(msg)
            self._push_log(msg)
            push_log_event(msg)  # Feed SSE stream for TUI ThoughtStream

            try:
                # Each successful phase completion pings the watchdog.
                # If any phase deadlocks, the ping ceases and systemd
                # detects the stall via WatchdogSec=15.

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
        await vector_memory.shutdown()  # TRACER BULLET: ensure coroutine is awaited
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
