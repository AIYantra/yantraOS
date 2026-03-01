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

I have the full context. Let me now craft the precise deliverables.[^1]

***

# YantraOS: Systemd Integration \& Watchdog Architecture

Here are the two production-grade artifacts for the Kriya Loop's autonomic nervous system, derived directly from the YANTRA_MASTER_CONTEXT architecture (§4.4, §4.7, §4.11).[^1]

***

## `yantra.service` — The Unit File

This is the complete, hardened systemd unit for `/etc/systemd/system/yantra.service`. Note the `WatchdogSec=30s` as specified by your task invariants, which overrides the `WatchdogSec=15` in §4.7 — adjust to your preference.[^1]

```ini
# /etc/systemd/system/yantra.service
# YantraOS Kriya Loop Daemon — Autonomic Nervous System
# Authority: Euryale Ferox Private Limited
# Ref: YANTRA_MASTER_CONTEXT §4.7 | Arch Invariant Override: WatchdogSec=30s

[Unit]
Description=YantraOS Kriya Loop Daemon — Karma Yogi Background Engine
Documentation=https://yantraos.com
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
# --- Process Identity & Security ---
Type=notify
User=yantra_daemon
Group=yantra

# --- Execution ---
ExecStart=/usr/bin/python3 /opt/yantra/core/engine.py
ExecStartPre=/bin/mkdir -p /run/yantra
ExecStartPre=/bin/chown yantra_daemon:yantra /run/yantra

# --- Resilience & Watchdog ---
Restart=on-failure
RestartSec=5s
WatchdogSec=30s

# --- Runtime Environment ---
Environment=YANTRA_HOME=/opt/yantra
Environment=PYTHONPATH=/opt/yantra
Environment=PYTHONUNBUFFERED=1

# --- Logging ---
StandardOutput=journal
StandardError=journal
SyslogIdentifier=yantra-kriya

# --- Hardening (Minimal Privilege Surface) ---
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/yantra /var/log/yantra /var/lib/yantra /run/yantra
ProtectHome=true

[Install]
WantedBy=multi-user.target
```


### Key Design Decisions

| Directive | Value | Rationale |
| :-- | :-- | :-- |
| `Type=notify` | — | Daemon gates `READY=1` behind subsystem verification; systemd will kill it if startup stalls [^1] |
| `WatchdogSec=30s` | 30s | Heartbeat expected every ~15s (half); missed beats trigger `SIGABRT` + restart [^1] |
| `Restart=on-failure` | `RestartSec=5s` | Recovers only from abnormal exits, not clean shutdowns; 5s delay prevents restart storms |
| `ProtectSystem=strict` + `ReadWritePaths` | Explicit allowlist | Daemon cannot write outside designated paths; protects host OS from rogue Skill payloads [^1] |
| `PYTHONPATH=/opt/yantra` | — | Resolves `ModuleNotFoundError: No module named 'core'` — a confirmed QEMU bootstrap failure mode per §13 [^1] |


***

## `engine.py` — The Python sdnotify Integration

This is the isolated Python block for `/opt/yantra/core/engine.py` demonstrating the full bootstrap sequence, subsystem verification, and the **deadlock-aware asynchronous watchdog**.

```python
# /opt/yantra/core/engine.py
# YantraOS Kriya Loop — Daemon Core with Autonomic Watchdog
# Ref: YANTRA_MASTER_CONTEXT §4.1, §4.2, §4.4, §4.7

import asyncio
import logging
import os
import time
import threading
from pathlib import Path

import sdnotify
import docker
import chromadb

# ---------------------------------------------------------------------------
# LOGGING — structured to journalctl (no timestamps; systemd adds them)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[YANTRA] %(levelname)s — %(message)s",
)
log = logging.getLogger("kriya")

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
WATCHDOG_PING_INTERVAL = 15          # seconds — half of WatchdogSec=30s
LOOP_SLEEP_INTERVAL    = 10          # seconds — §4.2: prevents CPU thrashing
IPC_SOCK_PATH          = Path("/run/yantra/ipc.sock")
CHROMA_DATA_PATH       = "/var/lib/yantra/chroma"
WATCHDOG_DEADLOCK_TIMEOUT = 60       # seconds — max silence before watchdog gives up

# ---------------------------------------------------------------------------
# GLOBAL HEARTBEAT STATE
# This is the inextricable link between liveness and cognitive progress.
# The watchdog thread ONLY pings systemd if this timestamp has advanced
# within WATCHDOG_DEADLOCK_TIMEOUT seconds. A frozen Kriya Loop = stale
# timestamp = watchdog silence = SIGABRT from systemd.
# ---------------------------------------------------------------------------
last_loop_time: float = 0.0
_loop_time_lock = threading.Lock()


def record_loop_advancement() -> None:
    """Called at each successful Kriya Loop iteration. Updates the heartbeat epoch."""
    global last_loop_time
    with _loop_time_lock:
        last_loop_time = time.monotonic()


def is_loop_alive() -> bool:
    """Returns True only if the cognitive loop has advanced within the deadlock window."""
    with _loop_time_lock:
        elapsed = time.monotonic() - last_loop_time
    return elapsed < WATCHDOG_DEADLOCK_TIMEOUT


# ---------------------------------------------------------------------------
# WATCHDOG THREAD — Async Heartbeat
# Sends WATCHDOG=1 to systemd every WATCHDOG_PING_INTERVAL seconds,
# BUT ONLY if is_loop_alive() confirms the main Kriya Loop is advancing.
# A corrupted LLM response or deadlocked queue starves this condition,
# causing watchdog silence → systemd dispatches SIGABRT.
# ---------------------------------------------------------------------------
def _watchdog_thread(notifier: sdnotify.SystemdNotifier) -> None:
    log.info("Watchdog heartbeat thread started. Interval: %ds", WATCHDOG_PING_INTERVAL)
    while True:
        time.sleep(WATCHDOG_PING_INTERVAL)
        if is_loop_alive():
            notifier.notify("WATCHDOG=1")
            log.debug("WATCHDOG=1 emitted — Kriya Loop is alive.")
        else:
            # Deliberately withhold the ping. Systemd will detect the missed
            # heartbeat at WatchdogSec=30s and dispatch SIGABRT + restart.
            log.critical(
                "DEADLOCK DETECTED — Kriya Loop has not advanced in %ds. "
                "Withholding WATCHDOG ping. Systemd will force restart.",
                WATCHDOG_DEADLOCK_TIMEOUT,
            )
            # Do NOT break — keep the thread alive to log further warnings
            # until systemd kills the process via SIGABRT.


# ---------------------------------------------------------------------------
# SUBSYSTEM VERIFICATION — Gates notifier.ready()
# notifier.ready() is emitted ONLY after ALL three critical subsystems
# are confirmed operational. §4.7: Type=notify design contract.
# ---------------------------------------------------------------------------
def _verify_docker_sandbox() -> None:
    """Verify Docker daemon is reachable and the socket is accessible."""
    notifier_status_ref.status("Verifying Docker sandbox...")  # type: ignore[name-defined]
    client = docker.from_env()
    client.ping()
    log.info("[✓] Docker sandbox: OPERATIONAL")


def _verify_ipc_socket() -> None:
    """Ensure the IPC socket directory exists and is writable by yantra_daemon."""
    notifier_status_ref.status("Verifying IPC socket...")  # type: ignore[name-defined]
    IPC_SOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Actual socket binding happens in bridge.py; here we confirm path integrity.
    if not os.access(IPC_SOCK_PATH.parent, os.W_OK):
        raise PermissionError(f"IPC socket dir not writable: {IPC_SOCK_PATH.parent}")
    log.info("[✓] IPC socket path: READY at %s", IPC_SOCK_PATH)


def _verify_chromadb() -> None:
    """Verify ChromaDB vector store is accessible and returns a valid heartbeat."""
    notifier_status_ref.status("Verifying ChromaDB vector memory...")  # type: ignore[name-defined]
    chroma_client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)
    chroma_client.heartbeat()  # raises on failure
    log.info("[✓] ChromaDB: OPERATIONAL at %s", CHROMA_DATA_PATH)


# ---------------------------------------------------------------------------
# BOOTSTRAP SEQUENCE
# ---------------------------------------------------------------------------
notifier_status_ref: sdnotify.SystemdNotifier | None = None  # set in main()


def bootstrap(notifier: sdnotify.SystemdNotifier) -> None:
    """
    Execute the full startup verification sequence.
    Raises on any subsystem failure — engine.py exits non-zero,
    systemd respects Restart=on-failure and retries after RestartSec=5s.
    """
    global notifier_status_ref
    notifier_status_ref = notifier

    notifier.status("Initializing Kriya Loop...")
    log.info("=== YantraOS Kriya Loop Bootstrap ===")

    _verify_docker_sandbox()
    _verify_ipc_socket()
    _verify_chromadb()

    # ALL critical subsystems confirmed — only NOW signal readiness to systemd.
    notifier.ready()
    log.info("READY=1 emitted. Kriya Loop entering active cycle.")
    notifier.status("Kriya Loop: ACTIVE")


# ---------------------------------------------------------------------------
# THE FOUR-PHASE KRIYA LOOP — §4.2
# ANALYZE → PATCH → TEST → UPDATE_ARCHITECTURE → (repeat)
# ---------------------------------------------------------------------------
async def _phase_analyze() -> None:
    """Scan system state: GPU/RAM/disk, evaluate pending skill queue."""
    log.info("[ANALYZE] Scanning system state...")
    await asyncio.sleep(0)          # yield to event loop


async def _phase_patch() -> None:
    """Pull updates, apply model weights, adjust routing config."""
    log.info("[PATCH] Applying pending patches...")
    await asyncio.sleep(0)


async def _phase_test() -> None:
    """Validate inference pipeline, run health checks."""
    log.info("[TEST] Validating inference pipeline...")
    await asyncio.sleep(0)


async def _phase_update_architecture() -> None:
    """Commit state changes, emit telemetry, rotate logs."""
    log.info("[UPDATE_ARCHITECTURE] Emitting telemetry, rotating logs...")
    await asyncio.sleep(0)


async def kriya_loop() -> None:
    """
    Main cognitive loop. On each successful iteration, record_loop_advancement()
    updates the heartbeat epoch — this is what keeps the watchdog ping alive.
    A hang in any phase (e.g., corrupted LLM response freezing _phase_patch)
    will stall record_loop_advancement(), starving the watchdog.
    """
    iteration = 0
    while True:
        iteration += 1
        log.info("── Kriya Cycle #%d ─────────────────────────────", iteration)
        try:
            await _phase_analyze()
            await _phase_patch()
            await _phase_test()
            await _phase_update_architecture()

            # ✅ ADVANCEMENT SIGNAL — only reached on full cycle completion
            record_loop_advancement()
            log.info("── Cycle #%d complete. Next in %ds. ───────────", iteration, LOOP_SLEEP_INTERVAL)

        except Exception as exc:
            # Log but do NOT crash — §4.2: error handling wraps the entire loop
            log.error("Kriya cycle #%d FAILED: %s", iteration, exc, exc_info=True)
            # NOTE: record_loop_advancement() is NOT called on failure.
            # Repeated failures will exhaust the WATCHDOG_DEADLOCK_TIMEOUT,
            # triggering the dead-man's switch.

        await asyncio.sleep(LOOP_SLEEP_INTERVAL)


# ---------------------------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------------------------
def main() -> None:
    notifier = sdnotify.SystemdNotifier()

    # Phase 1: Bootstrap + subsystem verification
    try:
        bootstrap(notifier)
    except Exception as exc:
        notifier.notify(f"STATUS=Bootstrap FAILED: {exc}")
        log.critical("Bootstrap failure — exiting for systemd restart: %s", exc)
        raise SystemExit(1) from exc

    # Phase 2: Seed the loop timestamp so watchdog doesn't fire immediately
    record_loop_advancement()

    # Phase 3: Launch asynchronous watchdog in a daemon thread
    watchdog = threading.Thread(
        target=_watchdog_thread,
        args=(notifier,),
        daemon=True,   # dies with the main process; systemd handles cleanup
        name="yantra-watchdog",
    )
    watchdog.start()

    # Phase 4: Run the Kriya Loop on the asyncio event loop (blocks forever)
    log.info("Entering Kriya Loop. PID: %d", os.getpid())
    asyncio.run(kriya_loop())


if __name__ == "__main__":
    main()
```


***

## Deadlock Prevention — The Core Mechanism

The critical invariant is the **dead-man's switch pattern**:[^1]

```
Main Kriya Loop advances → record_loop_advancement() updates timestamp
         ↓
Watchdog thread checks is_loop_alive() every 15s
         ↓
    Loop alive?  ──YES──→  notifier.notify("WATCHDOG=1")  → systemd satisfied
         │
         NO (timestamp stale > 60s, e.g., LLM response deadlock)
         │
         ↓
    Watchdog withholds ping → systemd sees no WATCHDOG=1 within WatchdogSec=30s
         ↓
    systemd dispatches SIGABRT → Restart=on-failure fires after RestartSec=5s
```

`record_loop_advancement()` is only called after all four phases complete successfully. A hang in `_phase_patch()` (e.g., a corrupted LLM stream blocking `await`) will stall it indefinitely, ensuring the watchdog naturally ceases pinging — no explicit deadlock detection code is required. This is a structural guarantee, not a conditional check.[^1]

***

## Activation Commands

```bash
# 1. Deploy the unit file
sudo cp yantra.service /etc/systemd/system/yantra.service

# 2. Reload systemd daemon registry
sudo systemctl daemon-reload

# 3. Enable on boot and start immediately
sudo systemctl enable --now yantra.service

# 4. Verify watchdog and notify handshake
sudo systemctl status yantra.service

# 5. Monitor live Kriya Loop output
sudo journalctl -u yantra.service -f --output=cat
```

<div align="center">⁂</div>

[^1]: YANTRA_MASTER_CONTEXT.md

