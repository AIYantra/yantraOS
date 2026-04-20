
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
[![Status](https://img.shields.io/badge/Status-v1.0%20Alpha%20Live-00FF41?style=for-the-badge)]()
[![Phase](https://img.shields.io/badge/Phase%204-Autonomous%20OTA%20Evolution-FFB000?style=for-the-badge)]()
[![IPC](https://img.shields.io/badge/IPC-UNIX%20Domain%20Socket-00FF41?style=for-the-badge&logo=linux&logoColor=000000)]()
[![Discord](https://img.shields.io/discord/1472285496129355847?color=00E5FF&label=Sovereign%20Fleet&logo=discord&logoColor=101010&style=for-the-badge)](https://discord.gg/tkg6XQBPpK)

<br/>

[![Open Collective Backers](https://img.shields.io/opencollective/backers/yantraos?style=for-the-badge&logo=opencollective&logoColor=ffffff&label=Backers&color=7B2FBE)](https://opencollective.com/yantraos)
[![Open Collective Sponsors](https://img.shields.io/opencollective/sponsors/yantraos?style=for-the-badge&logo=opencollective&logoColor=ffffff&label=Sponsors&color=E040FB)](https://opencollective.com/yantraos#section-contributors)

<br/>

[**`www.yantraos.com`**](https://yantraos.com) · [**`Documentation`**](https://yantraos.gitbook.io) · [**`Roadmap`**](https://github.com/orgs/AIYantra/projects) · [**`Discord`**](https://discord.gg/tkg6XQBPpK)

</div>

---

<div align="center">

```
┌───────────────────────────────────────────────────────────────┐
│  YOUR OS HAS BEEN PASSIVE FOR TOO LONG.                       │
│                                                               │
│  Every traditional OS is a hammer — it waits to be swung.    │
│                                                               │
│  YantraOS is a mind.                                          │
│  It reasons. It remembers. It acts. On its own.               │
└───────────────────────────────────────────────────────────────┘
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
┌──────────────────────────────────────────────────────────────┐
│              BARE-METAL ARCH LINUX                           │
│         (Boots to raw TTY1 — no display manager)            │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  PROCESS A: yantra.service (systemd daemon)                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  ┌─────────┐  ┌──────────┐  ┌────────────┐  ┌───────┐ │  │
│  │  │  SENSE  │→ │ REMEMBER │→ │   REASON   │→ │  ACT  │ │  │
│  │  │telemetry│  │ ChromaDB │  │  LiteLLM   │  │Docker │ │  │
│  │  │CPU/GPU  │  │ RAG/Vec  │  │Local/Cloud │  │Sandbox│ │  │
│  │  └─────────┘  └──────────┘  └────────────┘  └───────┘ │  │
│  │                    THE KRIYA LOOP                      │  │
│  └───────────────────────┬────────────────────────────────┘  │
│                          │                                   │
│              /run/yantra/ipc.sock                            │
│              (UNIX Domain Socket — IPC Bridge)               │
│                          │                                   │
│  PROCESS B: tui_shell.py (Textual UI, yantra_user)           │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ ╔══════════════╦═══════════════════════╦═════════════╗ │  │
│  │ ║  TELEMETRY   ║  THOUGHTSTREAM        ║  COMMAND    ║ │  │
│  │ ║  CPU:  12%   ║ [SENSE]  reading...   ║             ║ │  │
│  │ ║  RAM: 4.1GB  ║ [REASON] analyzing... ║             ║ │  │
│  │ ║  GPU:   0%   ║ [ACT]    exec done    ║  > _        ║ │  │
│  │ ╚══════════════╩═══════════════════════╩═════════════╝ │  │
│  │          Electric Blue · 3-Pane Textual HUD            │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### The Decoupling Guarantee

The daemon **cannot crash the UI**. The UI **cannot deadlock the engine**. They share only one thing: a structured JSON stream over a UNIX socket. The intelligence is sovereign.

---

## `03` · THE KRIYA LOOP

> *"Kriya"* — Sanskrit (क्रिया): Action. Specifically, purposeful, intentional action guided by conscious awareness.

This is the heartbeat of YantraOS. It runs perpetually inside `yantra.service`. It never pauses.

```
              ┌───────────────────────────────────┐
              │                                   │
        ┌─────▼──────┐                            │
        │   SENSE    │  CPU · RAM · GPU · Disk    │
        │            │  Logs · Network · Temps    │
        └─────┬──────┘                            │
              │                                   │
        ┌─────▼──────┐                            │
        │  REMEMBER  │  ChromaDB Vector Search    │
        │            │  Retrieve past context     │
        └─────┬──────┘                            │
              │                                   │
        ┌─────▼──────┐                            │
        │   REASON   │  LiteLLM Inference Call    │
        │            │  Local Model or Cloud API  │
        └─────┬──────┘                            │
              │                                   │
        ┌─────▼──────┐                            │
        │    ACT     │  Execute in Docker Sandbox │
        │            │  SSH (whitelisted cmds)    │
        └─────┬──────┘                            │
              │                                   │
        ┌─────▼──────┐                            │
        │    LEARN   │  Embed outcome in ChromaDB │
        │            │  Push heartbeat to Cloud   │
        └─────┬──────┘                            │
              │                                   │
              └───────────────────────────────────┘
                            ∞  forever
```

Each tick of the loop is a **cognitive cycle**. Your machine diagnoses itself, recalls what it has done before, reasons about what to do next, and acts — in a sandboxed, audited environment.

---

## `04` · THE HYBRID INFERENCE ENGINE

Hardware should not be a barrier to intelligence. YantraOS routes every inference request to the optimal backend based on what hardware is actually present.

```
         ┌─────────────────────────────────────────┐
         │           HARDWARE DETECTION             │
         └────────────────┬────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  ALPHA MODE     │ │   EDGE MODE     │ │   DARK MODE     │
│                 │ │                 │ │ (Net Offline)   │
│ NVIDIA / AMD    │ │ Integrated GPU  │ │                 │
│ VRAM >= 8 GB    │ │ CPU Only / Pi   │ │ Phi-3, Gemma-2B │
│                 │ │                 │ │ or halt ops     │
│ Ollama (Local)  │ │ Gemini 2.0 /   │ │                 │
│ Llama-3 70B     │ │ Claude / GPT-4o │ │ Graceful degrade│
│ 100% Offline    │ │ via LiteLLM    │ │ Offline ops only│
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

**The router is `LiteLLM`.** It abstracts every model behind a single unified API call. You write one reasoning call. LiteLLM decides the backend. Privacy is preserved by default — cloud is the exception, not the rule.

---

## `05` · THE SECURITY MODEL

An AI that can execute system commands is one of the most dangerous systems ever deployed on a personal machine. YantraOS takes this seriously.

```
  THREAT SURFACE ANALYSIS
  ═══════════════════════════════════════════════════════════════

  [X]  LLM hallucination → rm -rf /
  [✓]  MITIGATION: LLM output is NEVER executed on the host.

  [X]  Daemon privilege escalation
  [✓]  MITIGATION: Daemon runs as yantra_daemon (UID 999).

  [X]  Container escape to host filesystem
  [✓]  MITIGATION: Docker has NO network OR host mount.

  [X]  Unrestricted SSH command execution
  [✓]  MITIGATION: SSH key allows ONLY whitelisted commands.
              { systemctl restart X, pacman -Syu, ... }

  [X]  Secrets exfiltration via LLM prompt injection
  [✓]  MITIGATION: Secrets in /etc/yantra/secrets.env (0400).
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
╔══════════════════════════════════════════════════════════╗
║  Y A N T R A O S  ·  v1.0-alpha  ·  node: alpha-01      ║
╠══════════════════╦═══════════════════════╦═══════════════╣
║  TELEMETRY       ║  THOUGHTSTREAM        ║  COMMAND      ║
║                  ║                       ║               ║
║  CPU  ████░░ 12% ║ [SENSE]  reading...   ║               ║
║  RAM  ███░░░ 4.1G║ [REASON] analyzing... ║               ║
║  GPU  █░░░░░  3% ║ [ACT]    exec done    ║               ║
║  DISK ████░░  67%║ [LEARN]  embedding... ║               ║
║  NET  ↑12K ↓88K  ║                       ║               ║
║                  ║                       ║               ║
║  UPTIME 3d 14:22 ║                       ║  > _          ║
╚══════════════════╩═══════════════════════╩═══════════════╝
```

**Color system:** Electric Blue `#00E5FF` structural chrome · `#00FF41` telemetry confirmations · `#FFB000` alerts · `#888888` sub-text.

**Connects to the daemon via:** `/run/yantra/ipc.sock` — a UNIX Domain Socket streaming structured JSON telemetry every cycle.

---

## `07` · THE STACK

```
LAYER               TECHNOLOGY              PURPOSE
────────────────────────────────────────────────────────────────
Boot                Arch Linux (linux-lts)  Stable, minimal kernel
Init                systemd                 Daemon lifecycle + IPC
OS Interface        Python 3.12 / asyncio   Daemon orchestration
Inference Router    LiteLLM                 Model abstraction layer
Local Inference     Ollama                  Private on-device LLMs
Vector Memory       ChromaDB                Skill/context storage
Execution Sandbox   Docker + Alpine         Safe command execution
Host SSH Gateway    OpenSSH (allowlist)     Whitelisted host control
TUI Framework       Textual + Rich          Terminal HUD renderer
IPC Transport       UNIX Domain Socket      Daemon <-> UI bridge
Telemetry Cloud     Next.js + Supabase      Fleet monitoring
Deployment Host     Vercel                  www.yantraos.com
Secret Management   pydantic-settings       /etc/yantra/secrets.env
Filesystem          Btrfs (+ Snapper)       Atomic snapshots
Skill Store         Pinecone (1536-dim)     Semantic skill retrieval
OTA Manager         SystemD + pacman hook   Autonomous self-update
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
│   ├── cloud.py                 # Heartbeat to yantraos.com
│   ├── config.py                # pydantic-settings configuration
│   ├── tui_shell.py             # Textual TUI — the 3-pane HUD
│   └── sandbox/
│       └── Dockerfile           # Locked-down Alpine executor
│
├── deploy/                      # systemd service + polkit rules
├── docs/                        # Architecture diagrams
├── scripts/                     # OTA + maintenance scripts
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
  [linux-lts kernel] --> No display manager. No Wayland. No X11.
       │
       ▼
  [TTY1: raw terminal]
       │
       ├--> [systemd] starts yantra.service --> Kriya Loop begins ∞
       │             (runs as yantra_daemon)
       │
       └--> [auto-login: yantra_user]
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
| `ADR-007` | **Pinecone for Skill Store** | 1536-dim cosine index provides semantic retrieval for shareable autonomous behaviors across the fleet. |
| `ADR-008` | **OTA via systemd + pacman hooks** | Atomic, pre-snapshotted self-update avoids manual operator intervention while preserving rollback guarantees. |

---

## `12` · CURRENT STATE · v1.0 ALPHA LIVE

```
  MILESTONE TRACKER                    STATUS: v1.0 ALPHA LIVE [✓]
  ════════════════════════════════════════════════════════════════

  PHASE 1 — CORE DAEMON (COMPLETE)
  [✓] Kriya Loop orchestration (SENSE > REMEMBER > REASON > ACT > LEARN)
  [✓] Hardware telemetry probes (CPU / RAM / GPU)
  [✓] LiteLLM hybrid inference router (Local + Cloud fallback)
  [✓] ChromaDB async vector memory (graceful degradation)
  [✓] pydantic-settings configuration system

  PHASE 2 — IPC BRIDGE & TUI (COMPLETE)
  [✓] FastAPI ASGI over UNIX Domain Socket (/run/yantra/ipc.sock)
  [✓] Textual TUI — 3-pane HUD (Telemetry / ThoughtStream / Command)
  [✓] SSE ThoughtStream + /telemetry polling (2s cadence)
  [✓] Daemon <-> TUI mathematically decoupled
  [✓] systemd watchdog (WatchdogSec=15, phase-linked heartbeat)
  [✓] POST /command router — 8 registered actions:
        ping · status · get_phase · help
        pause_loop · resume_loop · inject_thought · shutdown

  PHASE 3 — SKILL STORE (COMPLETE)
  [✓] Pinecone yantra-skills index (1536-dim cosine)
  [✓] Skill schema v1 (yantraos/skill/v1) locked
  [✓] /api/skills/search — semantic RAG query endpoint live
  [✓] Web HUD Skill Store page (4 skills, category filter)
  [✓] Genesis probe record seeded

  PHASE 4 — AUTONOMOUS OTA EVOLUTION (COMPLETE)
  [✓] OTA Manager Web HUD page (/architecture)
  [✓] POST /api/ota/trigger — systemd-backed update pipeline
  [✓] BTRFS pre-snapshot before every OTA transaction
  [✓] Real-time OTA telemetry streamed to HUD
  [✓] Docker sandbox execution path verified on bare metal
  [✓] Compile ISO hardened (6-invariant rewrite)

  PHASE 5 — SYSTEM HARDENING & AI ANCHORING (COMPLETE)
  [✓] Patched AI environmental hallucination (anchored to bare-metal USB)
  [✓] Enforced strict IPv4 loopback constraints for IPC resiliency
  [✓] Stateless dynamic secrets injection pipeline (systemd drop-ins)
  [✓] Purged initramfs hooks / enforced minimal archiso + zstd compression
  [✓] Bypassed initramfs sulogin via SYSTEMD_SULOGIN_FORCE=1
  [✓] Autonomous dependency healing (LiteLLM cache Amnesia immunity)

  ONGOING
  [~] Restricted SSH whitelisted command gateway
  [ ] NVIDIA driver injection on live ISO
  [ ] Full LLM -> Docker -> SSH -> Host end-to-end test
  [ ] Multi-node fleet management (Alpha + Edge topology)
```

---

## `13` · CLOUD TELEMETRY

Every YantraOS node reports a heartbeat to the central fleet dashboard. Data is minimal and auditable.

```json
{
  "node_id":      "alpha-01",
  "timestamp":    "2026-03-27T00:00:00Z",
  "cpu_percent":  12.4,
  "ram_used_gb":  4.1,
  "vram_used_gb": 0.0,
  "last_action":  "scheduled fstrim",
  "loop_cycle":   14827,
  "routing":      "CLOUD_ONLY",
  "status":       "REASONING"
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
python3 -m core.daemon     # verify daemon starts clean
python3 -m core.tui_shell  # verify TUI connects to socket
git push origin feature/your-feature
# Open PR against main
```

---

## `14.5` · FUEL THE MACHINE ⚡

<div align="center">

<br/>

```
╔════════════════════════════════════════════════════════════════════╗
║                                                                    ║
║   YantraOS runs on bare metal.  Our infrastructure does not.       ║
║                                                                    ║
║   Every cycle of the Kriya Loop costs real compute.               ║
║   Every QA test on physical hardware costs real time.             ║
║   Every byte of open-source code costs real developer-hours.      ║
║                                                                    ║
║   If this project sparks something in you — fund the spark.       ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
```

<br/>

### 🌐 Open Collective · Fiscal Transparency Ledger

> All funding is **100% transparent**, **publicly auditable**, and **governed by our Open Collective**.  
> Every dollar in. Every dollar out. On-chain. In public.

<br/>

**[→ opencollective.com/yantraos](https://opencollective.com/yantraos)**

<br/>

---

### 🏛️ Where Your Capital Flows

<br/>

| 🔧 Infrastructure Matrix | 🖥️ Bare-Metal QA Lab | 👨‍💻 Core Developer Stipends |
|:---:|:---:|:---:|
| Cloud telemetry relay nodes, Supabase fleet DB, Vercel edge functions, Pinecone semantic index | Physical x86 test rigs, GPU validation hardware, network switches, KVM-over-IP units | Stipends for contributors maintaining the Kriya Loop, IPC bridge, and ISO build pipeline |

<br/>

---

### 🥇 Sponsors

*The organizations and individuals powering the Infrastructure Matrix.*

<br/>

[![Become a Sponsor](https://opencollective.com/yantraos/tiers/sponsors.svg?avatarHeight=80&width=800)](https://opencollective.com/yantraos#section-contributors)

<br/>

<a href="https://opencollective.com/yantraos#section-contributors">
  <img src="https://img.shields.io/opencollective/sponsors/yantraos?style=for-the-badge&logo=opencollective&logoColor=white&label=%E2%9A%A1%20Active%20Sponsors&color=7B2FBE" alt="Sponsors"/>
</a>

<br/><br/>

**[🚀 Become a Sponsor →](https://opencollective.com/yantraos)**

<br/>

---

### 🤝 Backers

*The community backbone keeping the Kriya Loop alive.*

<br/>

[![Become a Backer](https://opencollective.com/yantraos/tiers/backers.svg?avatarHeight=60&width=800)](https://opencollective.com/yantraos#section-contributors)

<br/>

<a href="https://opencollective.com/yantraos#section-contributors">
  <img src="https://img.shields.io/opencollective/backers/yantraos?style=for-the-badge&logo=opencollective&logoColor=white&label=%F0%9F%A4%9D%20Community%20Backers&color=E040FB" alt="Backers"/>
</a>

<br/><br/>

**[💜 Become a Backer →](https://opencollective.com/yantraos)**

<br/>

---

### 💡 Why Fund an Open-Source OS?

```
  THE VALUE PROPOSITION
  ═══════════════════════════════════════════════════════════════

  [✓]  100% open-source. Always. MIT licensed.
  [✓]  Zero VC funding. Zero proprietary lock-in.
  [✓]  Full fiscal transparency via Open Collective.
  [✓]  Your name/logo on this README forever.
  [✓]  Direct line to core architects for sponsors.
  [✓]  Early access to Phase 6: Multi-Node Fleet Intelligence.
```

<br/>

> *"The best infrastructure is the kind no one notices — until it's gone."*  
> *Fund what matters before it disappears.*

<br/>

[![Fund on Open Collective](https://img.shields.io/badge/Fund%20on%20Open%20Collective-7B2FBE?style=for-the-badge&logo=opencollective&logoColor=white)](https://opencollective.com/yantraos)

<br/>

</div>

---

## `15` · LICENSE & ACKNOWLEDGMENTS

Released under the **MIT License** — open metal, open mind.

**YantraOS stands on the shoulders of:**

```
  Arch Linux     — The minimal, rolling foundation
  systemd        — The init system that scales
  LiteLLM        — The model-agnostic inference layer
  Ollama         — Local LLM runtime
  ChromaDB       — Embedded vector database
  Pinecone       — Cloud-scale semantic skill store
  Textual / Rich — Terminal UI artistry
  Docker         — The sandbox that contains the blast
  Python         — The language of the AI frontier
```

---

<div align="center">

```
┌───────────────────────────────────────────────────────────┐
│                                                           │
│   The computer was always capable of thinking.           │
│   We just never asked it to.                             │
│                                                           │
│                              — YantraOS                  │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

**[`yantraos.com`](https://yantraos.com)** · **`/run/yantra/ipc.sock`** · **`∞`**

</div>
