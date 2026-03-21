
<div align="center">

```
██╗   ██╗ █████╗ ███╗   ██╗████████╗██████╗  █████╗  ██████╗ ███████╗
╚██╗ ██╔╝██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔══██╗██╔═══██╗██╔════╝
 ╚████╔╝ ███████║██╔██╗ ██║   ██║   ██████╔╝███████║██║   ██║███████╗
  ╚██╔╝  ██╔══██║██║╚██╗██║   ██║   ██╔══██╗██╔══██║██║   ██║╚════██║
   ██║   ██║  ██║██║ ╚████║   ██║   ██║  ██║██║  ██║╚██████╔╝███████║
   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
```

### `यन्त्र` — *Instrument. Engine. Autonomous Entity.*

**The world's first Autonomous Agent Operating System.**  
*It does not wait. It does not sleep. It thinks.*

<br/>

[![License: MIT](https://img.shields.io/badge/License-MIT-00FFFF?style=for-the-badge&logo=opensourceinitiative&logoColor=000000)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Platform-Arch%20Linux%20%7C%20Bare%20Metal-1793D1?style=for-the-badge&logo=archlinux&logoColor=white)](https://archlinux.org)
[![Engine](https://img.shields.io/badge/Engine-Python%203.12%20%7C%20Asyncio-FFD700?style=for-the-badge&logo=python&logoColor=000000)](https://python.org)
[![UI](https://img.shields.io/badge/Interface-Pure%20TUI%20%7C%20Textual-0057FF?style=for-the-badge&logo=gnometerminal&logoColor=white)]()
[![Status](https://img.shields.io/badge/Status-Phase%202%20Alpha%20%7C%20RC4%20Gold%20Master-00FF41?style=for-the-badge)]()
[![IPC](https://img.shields.io/badge/IPC-UNIX%20Domain%20Socket-00FF41?style=for-the-badge&logo=linux&logoColor=000000)]()

<br/>

[**`www.yantraos.com`**](https://yantraos.com) · [**`Documentation`**](https://yantraos.gitbook.io) · [**`Roadmap`**](https://github.com/orgs/YantraOS/projects/1) · [**`Discord`**](https://discord.gg/tkg6XQBPpK)

</div>

---

<div align="center">

```
┌─────────────────────────────────────────────────────────────────────┐
│  YOUR OS HAS BEEN PASSIVE FOR TOO LONG.                             │
│                                                                     │
│  Every traditional OS is a hammer — it waits for you to swing it.   │
│                                                                     │
│  YantraOS is a mind.                                                │
│  It reasons. It remembers. It acts. On its own.                     │
└─────────────────────────────────────────────────────────────────────┘
```

</div>

---

## `01` · THE PHILOSOPHY

> *"Yantra"* — Sanskrit (यन्त्र): A geometric instrument of divine computation. Used in Vedic cosmology to represent structured pathways through which consciousness operates on matter.

YantraOS is not a Linux distribution with AI bolted on. It is an **inversion of the computing paradigm**.

The conventional model: **Human → Input → OS → Output**

The YantraOS model: **OS senses context → OS reasons → OS acts → Human observes & overrides**

Your machine becomes an **autonomous entity** with goals, memory, and judgment. You are no longer an operator. You are a *principal* — the highest authority in a hierarchy of agents that manage your computational environment on your behalf.

---

## `02` · THE ARCHITECTURE

YantraOS is built on a **strict two-process, mathematically decoupled architecture**. No monolith. No race conditions between UI and intelligence.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         BARE-METAL ARCH LINUX                           │
│                    (Boots to raw TTY1 — no display manager)             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   PROCESS A: yantra.service (systemd daemon)                            │
│   ┌───────────────────────────────────────────────────────────────┐     │
│   │  ┌─────────┐   ┌──────────┐   ┌────────────┐   ┌──────────┐  │     │
│   │  │  SENSE  │→  │ REMEMBER │→  │   REASON   │→  │   ACT    │  │     │
│   │  │telemetry│   │ ChromaDB │   │  LiteLLM   │   │ Sandbox  │  │     │
│   │  │CPU/GPU  │   │ RAG/Vec  │   │ Local/Cloud│   │ Docker   │  │     │
│   │  └─────────┘   └──────────┘   └────────────┘   └──────────┘  │     │
│   │                         THE KRIYA LOOP                        │     │
│   └─────────────────────────┬─────────────────────────────────────┘     │
│                             │                                            │
│                    /run/yantra/ipc.sock                                  │
│                    (UNIX Domain Socket — IPC Bridge)                     │
│                             │                                            │
│   PROCESS B: tui_shell.py (Textual UI, runs as yantra_user)             │
│   ┌───────────────────────────────────────────────────────────────┐     │
│   │  ╔══════════════╦══════════════════════════╦════════════════╗  │     │
│   │  ║  TELEMETRY   ║  THOUGHTSTREAM           ║  COMMAND      ║  │     │
│   │  ║  CPU: 12%    ║ [SENSE] read             ║  > _          ║  │     │
│   │  ║  RAM: 4.1 GB ║ [REASON] act             ║               ║  │     │
│   │  ║  GPU: 0%     ║ [ACT] exec               ║               ║  │     │
│   │  ╚══════════════╩══════════════════════════╩════════════════╝  │     │
│   │              Electric Blue · 3-Pane Textual HUD                │     │
│   └───────────────────────────────────────────────────────────────┘     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### The Decoupling Guarantee

The daemon **cannot crash the UI**. The UI **cannot deadlock the engine**. They share only one thing: a structured JSON stream over a UNIX socket. The intelligence is sovereign.

---

## `03` · THE KRIYA LOOP

> *"Kriya"* — Sanskrit (क्रिया): Action. Specifically, purposeful, intentional action guided by conscious awareness.

This is the heartbeat of YantraOS. It runs perpetually inside `yantra.service`. It never pauses.

```
                    ┌──────────────────────────────────┐
                    │                                  │
              ┌─────▼──────┐                           │
              │   SENSE    │  CPU · RAM · GPU · Disk   │
              │            │  Logs · Network · Temps   │
              └─────┬──────┘                           │
                    │                                  │
              ┌─────▼──────┐                           │
              │  REMEMBER  │  ChromaDB Vector Search   │
              │            │  Retrieve past context    │
              └─────┬──────┘                           │
                    │                                  │
              ┌─────▼──────┐                           │
              │   REASON   │  LiteLLM Inference Call   │
              │            │  Local Model or Cloud API │
              └─────┬──────┘                           │
                    │                                  │
              ┌─────▼──────┐                           │
              │    ACT     │  Execute in Docker Sandbox│
              │            │  SSH back to host (whitelisted cmds) │
              └─────┬──────┘                           │
                    │                                  │
              ┌─────▼──────┐                           │
              │    LEARN   │  Embed outcome in ChromaDB│
              │            │  Push heartbeat to Cloud  │
              └─────┬──────┘                           │
                    │                                  │
                    └──────────────────────────────────┘
                              ∞  forever
```

Each tick of the loop is a **cognitive cycle**. Your machine diagnoses itself, recalls what it has done before, reasons about what to do next, and acts — in a sandboxed, audited environment.

---

## `04` · THE HYBRID INFERENCE ENGINE

Hardware should not be a barrier to intelligence. YantraOS routes every inference request to the optimal backend based on what hardware is actually present.

```
            ┌──────────────────────────────────────────────────────┐
            │                  HARDWARE DETECTION                  │
            └──────────────────────────┬───────────────────────────┘
                                       │
             ┌─────────────────────────┼───────────────────────────┐
             │                         │                           │
             ▼                         ▼                           ▼
  ┌──────────────────┐    ┌────────────────────┐    ┌─────────────────────┐
  │   ALPHA MODE     │    │    EDGE MODE        │    │   DARK MODE         │
  │                  │    │                     │    │  (Network Offline)  │
  │  NVIDIA RTX/A100 │    │  Integrated GPU /   │    │                     │
  │  AMD Radeon >8GB │    │  CPU Only / Pi      │    │  Tiny local models  │
  │                  │    │                     │    │  Phi-3, Gemma-2B    │
  │  Ollama (Local)  │    │  Gemini 2.0 /       │    │  or halt non-critical│
  │  Llama-3 70B     │    │  GPT-4o / Claude    │    │  Offline-only ops   │
  │  Qwen-2          │    │  via LiteLLM        │    │                     │
  │  100% Offline    │    │  Cloud API fallback │    │  Graceful degrades  │
  └──────────────────┘    └────────────────────┘    └─────────────────────┘
```

**The router is `LiteLLM`.** It abstracts every model behind a single unified API call. You write one reasoning call. LiteLLM decides the backend. Privacy is preserved by default — cloud is the exception, not the rule.

---

## `05` · THE SECURITY MODEL

An AI that can execute system commands is one of the most dangerous systems ever deployed on a personal machine. YantraOS takes this seriously.

```
  THREAT SURFACE ANALYSIS
  ═══════════════════════════════════════════════════════════════════════

  ❌  LLM hallucination → rm -rf /
  ✅  MITIGATION: LLM output is NEVER executed directly on the host.

  ❌  Daemon privilege escalation
  ✅  MITIGATION: Daemon runs as yantra_daemon (UID 999), NOT root.

  ❌  Container escape to host filesystem
  ✅  MITIGATION: Docker container has NO inherent network OR host mount.

  ❌  Unrestricted SSH command execution
  ✅  MITIGATION: SSH key permits ONLY whitelisted commands:
               { systemctl restart X, pacman -Syu, ... }

  ❌  Secrets exfiltration via LLM prompt injection
  ✅  MITIGATION: Secrets live in /etc/yantra/secrets.env (root:root 0400).
               Never interpolated into model context.
```

**The Execution Chain (for any system action):**

```
  LLM OUTPUT → JSON Schema Validation → Docker Container
      → Restricted Alpine Shell → SSH (whitelisted key)
          → Host Command Executor (allowlist only)
```

Nothing bypasses this chain. No exceptions. No overrides.

---

## `06` · THE TUI — YOUR WINDOW INTO THE MACHINE'S MIND

The UI is not a control panel. It is a **real-time window into the daemon's consciousness stream**.

```
╔══════════════════════════════════════════════════════════════════╗
║  Y A N T R A O S  ·  v0.6.0-pre-alpha  ·  node: alpha-01       ║
╠══════════════════╦═══════════════════════════╦═══════════════════╣
║  TELEMETRY       ║  THOUGHTSTREAM              ║  COMMAND        ║
║                  ║                             ║                 ║
║  CPU  ████░░  12%║ 22:47:01 [SENSE] Reading    ║                 ║
║  RAM  ███░░░ 4.1G║   /proc/meminfo ... ok      ║                 ║
║  GPU  █░░░░░  3% ║ 22:47:02 [REASON] Context:  ║                 ║
║  DISK ████░░  67%║   high I/O on /dev/sda ...  ║                 ║
║  NET  ↑12K ↓88K  ║ 22:47:03 [ACT] Scheduling  ║                 ║
║                  ║   fstrim --all              ║                 ║
║  UPTIME 3d 14:22 ║ 22:47:04 [LEARN] Embedding  ║  > _            ║
╚══════════════════╩═══════════════════════════╩═══════════════════╝
```

**Color system:** Electric Blue `#0057FF` structural chrome · `#00FFFF` telemetry live data · `#FF2D55` alerts · `#00FF41` action confirmations.

**Connects to the daemon via:** `/run/yantra/ipc.sock` — a UNIX Domain Socket streaming structured JSON telemetry every cycle.

---

## `07` · THE STACK

```
LAYER               TECHNOLOGY              PURPOSE
────────────────────────────────────────────────────────────────────
Boot                Arch Linux (linux-lts)  Stable, minimal kernel
Init                systemd                 Daemon lifecycle + IPC
OS Interface        Python 3.12 / asyncio   Daemon orchestration
Inference Router    LiteLLM                 Model abstraction layer
Local Inference     Ollama                  Private on-device LLMs
Vector Memory       ChromaDB                Skill/context storage
Execution Sandbox   Docker + Alpine         Safe command execution
Host SSH Gateway    OpenSSH (allowlist)     Whitelisted host control
TUI Framework       Textual + Rich          Terminal HUD renderer
IPC Transport       UNIX Domain Socket      Daemon ↔ UI bridge
Telemetry Cloud     Next.js + Supabase      Fleet monitoring
Deployment Host     Vercel                  www.yantraos.com
Secret Management   pydantic-settings       /etc/yantra/secrets.env
Filesystem          Btrfs (+ Snapper)       Atomic snapshots
```

---

## `08` · REPOSITORY ANATOMY

```
YantraOS/
│
├── archlive/                    # ArchISO build pipeline
│   ├── compile_iso.sh           # Master build orchestrator
│   ├── airootfs/                # Live filesystem overlay
│   │   ├── etc/                 # systemd units, users, sysctl
│   │   └── opt/yantra/          # Deployed daemon files
│   ├── packages.x86_64          # Package manifest
│   └── profiledef.sh            # ISO metadata
│
├── core/                        # The Cognitive Engine
│   ├── daemon.py                # Orchestrator: the Kriya Loop
│   ├── engine.py                # LLM reasoning + LiteLLM calls
│   ├── hardware.py              # CPU / RAM / GPU telemetry probes
│   ├── vector_memory.py         # ChromaDB async RAG interface
│   ├── ipc_server.py            # FastAPI UDS IPC — 8-action router
│   ├── cloud.py                 # Heartbeat → yantraos.com
│   ├── config.py                # pydantic-settings configuration
│   ├── tui_shell.py             # Textual TUI — the 3-pane HUD
│   └── sandbox/
│       └── Dockerfile           # Locked-down Alpine executor
│
├── deploy/                      # systemd service + polkit rules
├── docs/                        # Architecture diagrams
├── web/                         # Next.js cloud dashboard
│   └── src/app/api/
│       └── telemetry/ingest/    # Fleet heartbeat ingest API
│
├── config.yaml                  # Global daemon configuration
├── requirements.txt             # Python dependencies
└── YANTRA_MASTER_CONTEXT.md     # Living architecture specification
```

---

## `09` · BOOT SEQUENCE

```
  [BIOS/UEFI]
      │
      ▼
  [GRUB bootloader]
      │
      ▼
  [linux-lts kernel] ──→ No display manager. No Wayland. No X11.
      │
      ▼
  [TTY1: raw terminal]
      │
      ├──→ [systemd] starts yantra.service ──→ daemon.py runs as yantra_daemon
      │                                          Kriya Loop begins. ∞
      │
      └──→ [login: yantra_user] auto-login
               │
               ▼
           [tui_shell.py] launches Textual TUI
               │
               ├── Connects to /run/yantra/ipc.sock
               ├── Renders 3-pane HUD
               └── Streams live cognitive telemetry
```

Two processes. One socket. One mind.

---

## `10` · GETTING STARTED

> ⚠️ **Pre-Alpha Software.** Not for use as a primary OS. QEMU/VM testing is strongly recommended.

### Prerequisites

| Requirement | Minimum | Recommended |
|:---|:---:|:---:|
| RAM | 8 GB | 16 GB+ |
| Storage | 50 GB | 100 GB (Btrfs) |
| GPU | None (Cloud mode) | NVIDIA RTX (Local mode) |
| Network | Required at boot | Always-on for fleet mode |

### Build the ISO

```bash
# Clone the repository
git clone https://github.com/AIYantra/YantraOS.git
cd YantraOS

# Configure secrets (copy template and fill in your API keys)
cp host_secrets.env.template host_secrets.env
$EDITOR host_secrets.env

# Build the ArchISO (requires: archiso, Docker, root)
cd archlive
sudo bash compile_iso.sh
```

The ISO will be written to `archlive/out/yantraos-*.iso`.

### Test in QEMU

```bash
qemu-system-x86_64 \
  -m 4G \
  -enable-kvm \
  -cpu host \
  -drive file=archlive/out/yantraos-*.iso,format=raw,if=virtio \
  -nographic \
  -serial mon:stdio
```

### Run the Daemon Locally (Dev Mode)

```bash
# Create and activate virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the daemon (reads config.yaml + host_secrets.env)
python3 -m core.daemon

# In a second terminal, launch the TUI
python3 -m core.tui_shell
```

---

## `11` · ARCHITECTURAL DECISIONS

| ADR | Decision | Rationale |
|:---|:---|:---|
| `ADR-001` | **Python over Rust/Go** | Python unlocks LiteLLM, ChromaDB, PyTorch in weeks, not months. Performance-critical paths are earmarked for Rust rewrites in v2. |
| `ADR-002` | **Docker Sandbox for execution** | LLM hallucinations are real. No command ever touches the host directly. Docker provides a disposable blast radius. |
| `ADR-003` | **Arch Linux foundation** | Rolling release, bleeding-edge kernel, minimal bloat. We build exactly what we need. No Debian cruft to excise. |
| `ADR-004` | **Pure TUI, no display manager** | Eliminates Wayland/X11 complexity. Reduces attack surface. Maximizes stability on diverse hardware. |
| `ADR-005` | **UNIX socket IPC** | Zero-latency, zero-network-overhead communication between daemon and UI on the same host. No HTTP overhead. No port exposure. |
| `ADR-006` | **LiteLLM as router** | One API call, any model, any backend. Switching from Llama to Claude requires zero code changes in the engine. |

---

## `12` · CURRENT STATE · MILESTONE 9 — PHASE 2 ALPHA / RC4 ★

```
  MILESTONE TRACKER                              ▸ RC4 · BARE-METAL CONFIRMED ✓
  ════════════════════════════════════════════════════════════════════════════════

  [✓] Core Daemon orchestration loop (Kriya ∞)
  [✓] Hardware telemetry probes (CPU / RAM / Mock GPU)
  [✓] Cloud telemetry heartbeat (yantraos.com ingest live)
  [✓] ArchISO build pipeline (compile_iso.sh hardened)
  [✓] pydantic-settings config system (core/config.py)
  [✓] ChromaDB async vector memory (graceful degradation)
  [✓] LiteLLM inference router integration

  ── IPC BRIDGE & TUI ──────────────────────────────────────────────────────────
  [✓] FastAPI ASGI server over UNIX Domain Socket (/run/yantra/ipc.sock)
  [✓] Textual TUI — 3-pane HUD (Telemetry · ThoughtStream · Command prompt)
  [✓] Async IPC bridge: SSE ThoughtStream + /telemetry polling (2s cadence)
  [✓] Daemon ↔ TUI mathematically decoupled — daemon crash never kills TUI
  [✓] systemd watchdog integration (WatchdogSec=30, phase-linked ping)

  ── INTERACTIVE COMMAND ROUTER ★ NEW — BARE-METAL VERIFIED ───────────────────
  [✓] POST /command router — 8 registered actions:
        ping · status · get_phase · help
        pause_loop · resume_loop · inject_thought · shutdown
  [✓] pause_loop / resume_loop — operator halts & resumes autonomous Kriya
      execution; watchdog keepalive maintained during pause (no systemd kill)
  [✓] inject_thought — natural language injected into engine context_queue,
      consumed by REASON phase on the very next iteration tick
  [✓] RC4 BARE-METAL TEST PASSED:
        ▸ pause_loop confirmed — iterations halted on physical hardware
        ▸ inject_thought "My laptop fan is loud, please check CPU" — confirmed
          picked up by engine on next iteration, visible in ThoughtStream
        ▸ resume_loop confirmed — autonomous loop restored

  ── FLEET & EDGE TOPOLOGY (PHASE 2 ALPHA) ─────────────────────────────────────
  [✓] Docker sandbox execution pathway & TUI ThoughtStream logging
  [✓] Btrfs Snapper auto-snapshot integration
  [✓] Restricted SSH whitelisted command gateway (fleet_manager.py)
  [✓] Multi-node fleet management (Alpha + Edge topology)
  [✓] Full end-to-end LLM → Docker → SSH → Host test (Kriya Loop Audit)
  [✓] NVIDIA driver injection on live ISO (Nouveau Killswitch)

  ── ROADMAP ───────────────────────────────────────────────────────────────────
  [ ] Multi-GPU inference routing
  [ ] ARM architecture (Raspberry Pi 5) capability
  [ ] Yantra Skill Store (Public RAG Market)
```

---

## `13` · CLOUD TELEMETRY

Every YantraOS node reports a heartbeat to the central fleet dashboard. Data is minimal and auditable.

```
  Node: alpha-01
  Endpoint: POST https://www.yantraos.com/api/telemetry/ingest
  Auth: Bearer <YANTRA_TELEMETRY_TOKEN>
  Payload (JSON):
  {
    "node_id": "alpha-01",
    "timestamp": "2026-03-06T12:00:00Z",
    "cpu_percent": 12.4,
    "ram_used_gb": 4.1,
    "gpu_vram_used": "mocked",
    "last_action": "scheduled fstrim",
    "loop_cycle": 14827,
    "status": "REASONING"
  }
```

The cloud dashboard ([`www.yantraos.com`](https://yantraos.com)) aggregates fleet health, loop cycle counts, and action logs across all registered nodes.

---

## `14` · CONTRIBUTION

YantraOS is built in public. Contributions are accepted but the architecture is opinionated.

**Before opening a PR, understand the constraints:**
- Every new subsystem must fail **gracefully**. The Kriya Loop must never hard-crash.
- All AI-generated command execution must route through the Docker sandbox. No exceptions.
- The daemon and TUI are separate processes. They must remain decoupled via IPC.

```bash
# Development workflow
git checkout -b feature/your-feature
# ... implement ...
python3 -m core.daemon  # verify daemon starts clean
python3 -m core.tui_shell  # verify TUI connects to socket
git push origin feature/your-feature
# Open PR against main
```

---

## `15` · LICENSE & ACKNOWLEDGMENTS

Released under the **MIT License** — open metal, open mind.

**YantraOS stands on the shoulders of:**

```
  Arch Linux          — The minimal, rolling foundation
  systemd             — The init system that scales
  LiteLLM             — The model-agnostic inference layer
  Ollama              — Local LLM runtime
  ChromaDB            — Embedded vector database
  Textual / Rich      — Terminal UI artistry
  Docker              — The sandbox that contains the blast
  Python              — The language of the AI frontier
```

---

<div align="center">

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   The computer was always capable of thinking.         │
│   We just never asked it to.                           │
│                                                         │
│                         — YantraOS                      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**[`yantraos.com`](https://yantraos.com)** · **`/run/yantra/ipc.sock`** · **`∞`**

</div>
