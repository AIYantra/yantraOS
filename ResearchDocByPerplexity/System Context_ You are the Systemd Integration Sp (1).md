<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# System Context: You are the Systemd Integration Specialist and Anomaly Debugger for "YantraOS". You have been provided with the YANTRA_MASTER_CONTEXT.md file. Review it carefully, particularly Section 4 (The Kriya Loop) and Milestone 5 of the architectural blueprint.

+4

Task: We need to establish the autonomic nervous system of the Kriya Loop to ensure relentless 24/7 uptime. Draft the exact systemd unit file and the corresponding Python sdnotify integration logic for the main daemon (engine.py).
+1

Strict Architectural Invariants:

1. The Unit File (/etc/systemd/system/yantra.service): * Must utilize Type=notify. * Must set WatchdogSec=30s. * Must execute securely under User=yantra_daemon and Group=yantra. * Must enforce startup ordering: After=network-online.target docker.service and Wants=network-online.target docker.service. * Must include Restart=on-failure with a 5-second delay (RestartSec=5s).
+4
2. The Python Logic (/opt/yantra/core/engine.py snippet): * Must import and instantiate notifier = sdnotify.Notifier(). * Must emit notifier.status("Initializing Kriya Loop...") during the bootstrap sequence. * Must emit notifier.ready() ONLY after critical subsystems (Docker sandbox, IPC socket, ChromaDB) are verified operational.
+2

CRITICAL DEADLOCK PREVENTION: You must implement the asynchronous heartbeat. It must send notifier.notify("WATCHDOG=1") every 15 seconds. However, this ping must be inextricably linked to the successful advancement of the main cognitive loop (e.g., updating a last_loop_time timestamp). If the main work queue deadlocks (e.g., stuck on a corrupted LLM response), the watchdog ping must inherently cease, forcing systemd to detect the failure and dispatch a SIGABRT.
+1

Output: Provide the .service file configuration and the isolated Python code block demonstrating the secure heartbeat integration.

I now have complete context from the YANTRA_MASTER_CONTEXT.md. I have everything I need — Section 4 (Kriya Loop), the daemon stack, permissions matrix, systemd unit spec, and Milestone 5 (Component Architecture Matrix). Let me now draft the production-grade artifacts.

***

Here is the complete, production-hardened systemd unit file and Python `sdnotify` integration for the YantraOS Kriya Loop daemon, built strictly against the architectural invariants in your master context.[^1]

***

## `/etc/systemd/system/yantra.service`

This unit file uses `Restart=on-failure` as specified in your invariants (not `Restart=always` from §4.7), enforces `WatchdogSec=30s` per the task spec, and pins critical startup ordering. Note that `PYTHONPATH=/opt/yantra` is retained from the Milestone 13 systemd patch that resolved the `ModuleNotFoundError` during native QEMU bootstrap.[^1]

```ini
# /etc/systemd/system/yantra.service
# YantraOS Kriya Loop Daemon — Autonomic Nervous System
# Authority: Euryale Ferox Private Limited
# Classification: PRODUCTION — systemd Unit v2.0

[Unit]
Description=YantraOS Kriya Loop Daemon — Relentless 24/7 Autonomous Worker
Documentation=https://yantraos.com/docs
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
# --- Process Identity (Non-Root Enforcement, see §4.6 Permissions Matrix) ---
Type=notify
User=yantra_daemon
Group=yantra

# --- Execution ---
ExecStart=/usr/bin/python3 /opt/yantra/core/engine.py
ExecReload=/bin/kill -HUP $MAINPID

# --- Resilience & Watchdog ---
# WatchdogSec=30s: systemd will send SIGABRT if WATCHDOG=1 is not received
# within the window. The Python heartbeat fires every 15s (half interval),
# guaranteeing 2 missed pings before termination — a safe margin.
Restart=on-failure
RestartSec=5s
WatchdogSec=30s

# --- Environment ---
Environment=YANTRA_HOME=/opt/yantra
# Milestone 13 patch: resolves ModuleNotFoundError for 'core' namespace
Environment=PYTHONPATH=/opt/yantra

# --- Resource & Security Hardening ---
# Prevent privilege escalation from within the daemon process
NoNewPrivileges=true
# Restrict writes to specific paths only
ReadWritePaths=/opt/yantra /var/log/yantra /var/lib/yantra /run/yantra
# Protect system directories
ProtectSystem=strict
ProtectHome=true
# Lock down kernel tunables
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
# Restrict address families to UNIX sockets and TCP/IP (IPC + telemetry)
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
# Deny dangerous syscalls (no kernel module loading, etc.)
SystemCallFilter=@system-service
RuntimeDirectory=yantra
RuntimeDirectoryMode=0750

# --- Logging ---
StandardOutput=journal
StandardError=journal
SyslogIdentifier=yantra-kriya

[Install]
WantedBy=multi-user.target
```


***

## `/opt/yantra/core/engine.py` — Secure Heartbeat Integration

The architecture of the deadlock prevention is the critical piece. The watchdog ping is **not on a fixed timer** — it is gated by a `last_loop_time` timestamp that the main cognitive loop updates at the end of every successful iteration. If the work queue deadlocks (e.g., blocking on a corrupted LLM stream), `last_loop_time` stalls. The heartbeat thread detects the stall via `WATCHDOG_STALL_THRESHOLD` and voluntarily ceases pinging, allowing `WatchdogSec=30s` to trigger `SIGABRT` and force a clean restart.[^1]

```python
# /opt/yantra/core/engine.py
# YantraOS Kriya Loop — Main Daemon Orchestrator
# Autonomic Nervous System: sdnotify + systemd Watchdog Integration
# Authority: Euryale Ferox Private Limited | Phase 1 (Days 1-4)

import asyncio
import logging
import os
import signal
import socket
import threading
import time
from pathlib import Path
from typing import Optional

import sdnotify
import docker
import chromadb

# ── Sibling core modules (resolved via PYTHONPATH=/opt/yantra) ──────────────
from core.hardware import detect_hardware_capability
from core.router import KriyaRouter
from core.memory import VectorMemory

# ── Logging Configuration ────────────────────────────────────────────────────
LOG_PATH = Path("/var/log/yantra/engine.log")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] KRIYA :: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("yantra.engine")

# ── Constants ────────────────────────────────────────────────────────────────
IPC_SOCKET_PATH = Path("/run/yantra/ipc.sock")
LOOP_SLEEP_INTERVAL = 10          # seconds between Kriya iterations (§4.2)
WATCHDOG_PING_INTERVAL = 15       # seconds between WATCHDOG=1 pings (< WatchdogSec/2)
WATCHDOG_STALL_THRESHOLD = 25     # seconds of no loop advancement before pings cease

# ── Global Shared State (thread-safe via Lock) ───────────────────────────────
_state_lock = threading.Lock()
_last_loop_time: Optional[float] = None   # Updated by main loop; read by watchdog thread
_shutdown_event = threading.Event()       # Set on SIGTERM/SIGINT to gracefully exit


def update_loop_heartbeat() -> None:
    """Called by the main cognitive loop at the END of each successful iteration.
    This is the single source of truth for 'is the loop alive?'
    The watchdog thread reads this. If it stops updating → pings cease → SIGABRT.
    """
    global _last_loop_time
    with _state_lock:
        _last_loop_time = time.monotonic()


def _watchdog_thread_fn(notifier: sdnotify.SystemdNotifier) -> None:
    """
    CRITICAL DEADLOCK PREVENTION — Asynchronous Watchdog Heartbeat Thread.

    Design Invariant:
        The WATCHDOG=1 ping is INEXTRICABLY LINKED to the main loop's liveness.
        A fixed-interval timer would mask deadlocks. Instead, we verify that
        `_last_loop_time` has advanced within WATCHDOG_STALL_THRESHOLD seconds.

    Failure Mode:
        If the main work queue deadlocks (e.g., stuck on corrupted LLM response,
        blocked IPC socket, ChromaDB lock), `update_loop_heartbeat()` stops being
        called. After WATCHDOG_STALL_THRESHOLD seconds, this thread STOPS sending
        WATCHDOG=1. systemd detects the silence within WatchdogSec=30s and
        dispatches SIGABRT, forcing a clean restart via Restart=on-failure.
    """
    log.info("Watchdog thread armed. Ping interval: %ds | Stall threshold: %ds",
             WATCHDOG_PING_INTERVAL, WATCHDOG_STALL_THRESHOLD)

    while not _shutdown_event.is_set():
        time.sleep(WATCHDOG_PING_INTERVAL)

        if _shutdown_event.is_set():
            break

        with _state_lock:
            last = _last_loop_time

        if last is None:
            # Engine still bootstrapping — do not ping yet
            log.debug("Watchdog: engine still initializing, withholding ping.")
            continue

        elapsed_since_last_loop = time.monotonic() - last

        if elapsed_since_last_loop <= WATCHDOG_STALL_THRESHOLD:
            # Main loop is alive and advancing — send the heartbeat
            notifier.notify("WATCHDOG=1")
            log.debug("Watchdog: WATCHDOG=1 sent (loop age: %.1fs)", elapsed_since_last_loop)
        else:
            # !! STALL DETECTED — deliberately withhold the ping !!
            # systemd will fire SIGABRT within WatchdogSec=30s of last ping.
            log.critical(
                "WATCHDOG STALL DETECTED: Main loop has not advanced in %.1fs "
                "(threshold: %ds). Withholding WATCHDOG=1 ping. "
                "systemd will trigger SIGABRT and force restart.",
                elapsed_since_last_loop,
                WATCHDOG_STALL_THRESHOLD,
            )
            # Do NOT call notifier.notify("WATCHDOG=1") — intentional silence


def _verify_docker_sandbox() -> bool:
    """Verify the Docker daemon is reachable and the socket is accessible."""
    try:
        client = docker.from_env()
        client.ping()
        log.info("[SUBSYSTEM] Docker sandbox: OPERATIONAL")
        return True
    except Exception as e:
        log.error("[SUBSYSTEM] Docker sandbox: FAILED — %s", e)
        return False


def _verify_ipc_socket() -> bool:
    """Verify the UNIX domain IPC socket path is writable (TUI ↔ daemon bridge)."""
    try:
        IPC_SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Attempt to bind briefly to confirm socket availability
        test_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bind_path = str(IPC_SOCKET_PATH) + ".probe"
        test_sock.bind(bind_path)
        test_sock.close()
        os.unlink(bind_path)
        log.info("[SUBSYSTEM] IPC socket path: OPERATIONAL (%s)", IPC_SOCKET_PATH)
        return True
    except Exception as e:
        log.error("[SUBSYSTEM] IPC socket: FAILED — %s", e)
        return False


def _verify_chromadb() -> bool:
    """Verify ChromaDB vector store is accessible at its persistent path."""
    try:
        chroma_path = os.environ.get("YANTRA_HOME", "/opt/yantra") + "/data/chroma"
        client = chromadb.PersistentClient(path=chroma_path)
        # Heartbeat call — raises on connection failure
        client.heartbeat()
        log.info("[SUBSYSTEM] ChromaDB (Vector Memory): OPERATIONAL (%s)", chroma_path)
        return True
    except Exception as e:
        log.error("[SUBSYSTEM] ChromaDB: FAILED — %s", e)
        return False


def bootstrap_and_notify(notifier: sdnotify.SystemdNotifier) -> bool:
    """
    Execute the full bootstrap sequence and emit sdnotify signals.

    Sequence:
        1. Status: "Initializing Kriya Loop..." (immediate)
        2. Verify all 3 critical subsystems
        3. notifier.ready() ONLY if ALL subsystems pass (§ Architectural Invariant 2)

    Returns:
        True if all subsystems are operational and READY=1 was sent.
        False if any critical subsystem failed (daemon should exit, systemd will restart).
    """
    # ── Emit status immediately on startup ──────────────────────────────────
    notifier.status("Initializing Kriya Loop...")
    log.info("═══════════════════════════════════════════════════")
    log.info("  YantraOS Kriya Loop — Bootstrap Sequence Begin  ")
    log.info("═══════════════════════════════════════════════════")

    # ── Hardware Detection ───────────────────────────────────────────────────
    notifier.status("Probing hardware capability...")
    try:
        hw_capability = detect_hardware_capability()
        log.info("[SUBSYSTEM] Hardware: %s", hw_capability)
    except Exception as e:
        log.error("[SUBSYSTEM] Hardware detection failed: %s", e)
        notifier.status("BOOT FAILED: Hardware detection error")
        return False

    # ── Critical Subsystem Verification ─────────────────────────────────────
    notifier.status("Verifying critical subsystems: Docker, IPC, ChromaDB...")

    checks = {
        "Docker Sandbox": _verify_docker_sandbox(),
        "IPC Socket":     _verify_ipc_socket(),
        "ChromaDB":       _verify_chromadb(),
    }

    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        log.critical(
            "Bootstrap FAILED. Critical subsystems offline: %s. "
            "Daemon will exit. systemd Restart=on-failure will retry in 5s.",
            ", ".join(failed)
        )
        notifier.status(f"BOOT FAILED: {', '.join(failed)} unavailable")
        return False

    # ── All Subsystems Verified — Emit READY=1 ──────────────────────────────
    # THIS IS THE ONLY PLACE notifier.ready() is called (Architectural Invariant 2)
    notifier.ready()
    notifier.status("Kriya Loop ACTIVE — All subsystems nominal.")
    log.info("READY=1 emitted to systemd. Kriya Loop entering operational state.")
    return True


def run_kriya_loop(notifier: sdnotify.SystemdNotifier) -> None:
    """
    The Four-Phase Cognitive Loop: ANALYZE → PATCH → TEST → UPDATE_ARCHITECTURE
    Runs indefinitely, gated by _shutdown_event.

    Each successful full-cycle iteration calls update_loop_heartbeat() to signal
    liveness to the watchdog thread. A deadlock in any phase will cause the
    heartbeat to stall, triggering systemd SIGABRT via watchdog silence.
    """
    router = KriyaRouter()
    memory = VectorMemory()
    iteration = 0

    while not _shutdown_event.is_set():
        iteration += 1
        log.info("── Kriya Cycle #%d BEGIN ──", iteration)

        try:
            # ── Phase 1: ANALYZE ────────────────────────────────────────────
            notifier.status(f"Cycle #{iteration} | Phase: ANALYZE")
            log.info("[ANALYZE] Scanning system state and skill queue...")
            # TODO: Implement full ANALYZE logic (hardware scan, queue eval)
            # Any blocking call here that deadlocks will stall update_loop_heartbeat()

            # ── Phase 2: PATCH ──────────────────────────────────────────────
            notifier.status(f"Cycle #{iteration} | Phase: PATCH")
            log.info("[PATCH] Applying pending updates and routing adjustments...")
            # TODO: Implement PATCH logic (model weight updates, config adjust)

            # ── Phase 3: TEST ───────────────────────────────────────────────
            notifier.status(f"Cycle #{iteration} | Phase: TEST")
            log.info("[TEST] Validating inference pipeline and health checks...")
            # TODO: Implement TEST logic (inference pipeline health check)

            # ── Phase 4: UPDATE_ARCHITECTURE ────────────────────────────────
            notifier.status(f"Cycle #{iteration} | Phase: UPDATE_ARCHITECTURE")
            log.info("[UPDATE_ARCHITECTURE] Committing state, emitting telemetry...")
            # TODO: Implement telemetry emission (§6: WebSocket, HTTP POST, IPC)

            # ── LOOP HEARTBEAT: Must be the FINAL act of a successful cycle ──
            # If execution never reaches this line (deadlock above), the watchdog
            # thread will detect the stall and cease pinging systemd.
            update_loop_heartbeat()
            log.info("── Kriya Cycle #%d COMPLETE ──", iteration)

        except Exception as e:
            # Log but do NOT crash — daemon must be resilient (§4.2)
            log.error("Kriya Cycle #%d unhandled exception: %s", iteration, e, exc_info=True)
            # NOTE: update_loop_heartbeat() is NOT called on exception.
            # Repeated failures will stall the heartbeat → watchdog SIGABRT.

        # Prevent CPU thrashing between iterations (§4.2: time.sleep(10))
        _shutdown_event.wait(timeout=LOOP_SLEEP_INTERVAL)

    log.info("Kriya Loop exited cleanly via shutdown signal.")


def _handle_shutdown(signum, frame) -> None:
    """Graceful shutdown handler for SIGTERM / SIGINT."""
    log.info("Received signal %d — initiating graceful shutdown...", signum)
    _shutdown_event.set()


def main() -> None:
    """
    Daemon entry point.

    Flow:
        1. Instantiate sdnotify.SystemdNotifier
        2. Register signal handlers
        3. Bootstrap + verify subsystems → emit READY=1
        4. Arm watchdog thread
        5. Enter Kriya cognitive loop
        6. Clean exit on shutdown
    """
    # ── sdnotify Instantiation (Architectural Invariant 2) ──────────────────
    notifier = sdnotify.SystemdNotifier()

    # ── Signal Handlers ──────────────────────────────────────────────────────
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    # ── Bootstrap Sequence ───────────────────────────────────────────────────
    if not bootstrap_and_notify(notifier):
        log.critical("Bootstrap failed. Exiting with code 1.")
        raise SystemExit(1)

    # ── Arm Watchdog Thread ──────────────────────────────────────────────────
    watchdog = threading.Thread(
        target=_watchdog_thread_fn,
        args=(notifier,),
        name="yantra-watchdog",
        daemon=True,   # Dies automatically when main thread exits
    )
    watchdog.start()
    log.info("Watchdog thread armed: %s", watchdog.name)

    # ── Enter Cognitive Loop ─────────────────────────────────────────────────
    run_kriya_loop(notifier)

    # ── Graceful Shutdown ────────────────────────────────────────────────────
    notifier.notify("STOPPING=1")
    log.info("STOPPING=1 emitted. YantraOS Kriya Loop daemon halted.")


if __name__ == "__main__":
    main()
```


***

## Key Design Decisions Explained

### Deadlock Prevention Architecture

The critical insight is that the watchdog ping is **not self-sufficient** — it cannot fire unless the main loop has recently completed a cycle. The `_last_loop_time` timestamp acts as a cryptographic proof-of-work: `WATCHDOG=1` is only emitted when `elapsed_since_last_loop <= WATCHDOG_STALL_THRESHOLD`.[^1]

```
Main Loop Cycle:          ANALYZE → PATCH → TEST → UPDATE → update_loop_heartbeat()
                                                                       ↓
                                                          _last_loop_time = time.monotonic()
                                                                       ↓
Watchdog Thread checks:   elapsed <= 25s? → send WATCHDOG=1 ✓
                          elapsed >  25s? → SILENCE          ← systemd fires SIGABRT within 30s
```


### Why `WatchdogSec=30s` with 15s ping interval

The `WATCHDOG_PING_INTERVAL=15` is exactly half of `WatchdogSec=30s`, following the systemd documentation best practice of pinging at half the watchdog interval. This provides one full missed-ping cycle as a buffer before termination.[^1]

### `notifier.ready()` Gating

The `READY=1` signal is emitted **only after all three critical subsystems** — Docker sandbox, IPC socket, and ChromaDB — are verified operational. This prevents systemd from marking the service as started while it is actually still broken, which would cause `After=` dependencies in downstream units to activate prematurely.[^1]

### `STOPPING=1` on Clean Exit

When `SIGTERM` is received (e.g., `systemctl stop yantra`), the daemon sets `_shutdown_event`, which breaks both the main loop and the watchdog's `time.sleep`. A final `notifier.notify("STOPPING=1")` tells systemd the process is intentionally stopping, preventing it from counting the exit as a failure against `Restart=on-failure`.
<span style="display:none">[^2]</span>

<div align="center">⁂</div>

[^1]: YANTRA_MASTER_CONTEXT.md

[^2]: YANTRA_MASTER_CONTEXT.md

