# YANTRA_MASTER_CONTEXT.md — Unified Engine Memory

> **Version:** 4.0.0 | **Generated:** 2026-03-14 | **Classification:** MASTER REFERENCE — DO NOT FRAGMENT
>
> **Authority:** Euryale Ferox Private Limited | **Clearance:** Lead Architect

---

## 1. Brand & Aesthetic Rules

### 1.1 Design Tokens (Immutable)

| Token          | Value     | Usage                                    |
|----------------|-----------|------------------------------------------|
| `background`   | `#1E1E1E` | Base canvas for all pages / TUI containers |
| `surface`      | `#2A2A2A` | Secondary panels, data cards             |
| `accent`       | `#00E5FF` | Electric Blue — borders, links, glows, active states |
| `alert`        | `#FFB000` | Terminal Amber — warnings, system states |
| `text-primary` | `#E0E0E0` | Body text                                |
| `text-dim`     | `#888888` | Sub-text, metadata                       |
| `terminal-bg`  | `#101010` | Terminal HUD dark background             |
| `tui-bg`       | `#121212` | Yantra Shell TUI background (Phase 2 spec) |

### 1.2 Typography

| Font              | Role                                      |
|-------------------|-------------------------------------------|
| **JetBrains Mono** | All headings, terminal HUD readouts, code |
| **Inter**          | Body text, paragraphs, sub-headlines      |
| **Monospace / Nerd Font** | Yantra Shell TUI (terminal)        |

### 1.3 The Geometric Law (INVIOLABLE)

```css
border-radius: 0px; /* ALWAYS. No exceptions. */
```

Any UI element with `rounded-*`, `rounded-md`, `border-radius > 0px`, or any similar softening is **a protocol violation**. Enforced globally in `globals.css` via `border-radius: 0 !important` and in `tailwind.config.ts` with all `borderRadius` values set to `0px`. In the TUI, this translates to sharp, continuous line borders (`border: solid $electric_blue;`) — no curved widgets.

### 1.4 Interaction Feel

- Hover borders: **instantaneous snap** to `#00E5FF` — no CSS `transition` property. Machine-feel, not organic.
- 1px gaps between cards render as seamless grid lines.
- Interface must feel like a **precision instrument** — advanced sci-fi telemetry equipment, not a standard web app.

### 1.5 Brand Philosophy

YantraOS is derived from the Sanskrit for **machine, instrument, or engine utilized to focus energy**. It operates under the philosophical framework of a **"Karma Yogi"** — a relentless, background entity that continuously organizes, optimizes, and heals the system environment 24/7 without user intervention. It is explicitly designed as a **Level 3 AI-Agent Operating System** built as a native orchestration layer on top of Arch Linux. The platform solves the **"AI Accessibility Gap"** (where local AI requires expensive GPUs, excluding 90% of users) by employing a "Hybrid Advantage"—combining local privacy and zero latency with cloud power for complex reasoning.

---

## 2. Deployed Web HUD Architecture

### 2.1 Core Stack

| Layer              | Technology                          | Version       |
|--------------------|-------------------------------------|---------------|
| Framework          | Next.js (App Router)                | 14.2.29       |
| Language           | TypeScript + TSX                    | ^5            |
| Styling            | Tailwind CSS (geometric only)       | ^3.4.1        |
| Animation          | Framer Motion                       | ^11.18.2      |
| AI SDK             | Vercel AI SDK (`ai`)                | ^6.0.97       |
| AI Provider        | `@ai-sdk/google` (Gemini 2.0 Flash) | ^3.0.30      |
| Vector DB Client   | `@pinecone-database/pinecone`       | ^7.1.0        |
| UI Components      | 21st.dev / Aceternity (EvervaultCard, BackgroundBeams, BackgroundPaths) | Custom |
| Icons              | Lucide React                        | ^0.575.0      |
| Hosting            | Vercel                              | Production    |
| Repository         | `osyantra/yantraos-web-hud` (private) | `main` branch |

### 2.2 Environment Variables (Production)

```env
PINECONE_API_KEY=<secret>
GOOGLE_GENERATIVE_AI_API_KEY=<secret>   # Required by @ai-sdk/google
NEXT_PUBLIC_SITE_URL=https://yantraos.com
```

> **WARNING:** The env var name is `GOOGLE_GENERATIVE_AI_API_KEY`, NOT `GEMINI_API_KEY`. Enforced by the `@ai-sdk/google` provider.

### 2.3 Production URL

```
https://yantraos.com
```

### 2.4 Page Architecture & Routing

| Route             | Status | Components                               |
|-------------------|--------|------------------------------------------|
| `/`               | ✅ LIVE | NavBar, TerminalHUD, TelemetryStrip (Polling 5s), EngineRoom, SkillStore |
| `/skill-store`    | 🔲 TODO | Skill grid + Pinecone semantic search   |
| `/architecture`   | 🔲 TODO | Architecture docs viewer                |
| `/docs`           | 🔲 TODO | RAG documentation browser               |
| `/api/health`     | ✅ LIVE | GET — Merges live Kriya Cache + Pinecone Health |
| `/api/telemetry/ingest` | ✅ LIVE | POST — Validates and caches live daemon telemetry |
| `/api/skills/search` | ✅ LIVE | GET `?query=X` — RAG search against Pinecone `yantra-memory` |
| `/api/kriya/execute` | ✅ LIVE | POST — Streaming inference via Vercel AI SDK + Gemini 2.0 Flash |

### 2.5 Component Inventory

| Component              | Purpose                                                |
|------------------------|--------------------------------------------------------|
| `NavBar`               | `YANTRA_OS` + blinking cursor, nav links, 1px `#00E5FF` bottom border |
| `TerminalHUD`          | Interactive console: boot sequence → live command input |
| `TerminalTypewriter`   | Multi-line sequential terminal output simulation       |
| `TelemetryStrip`       | Live indicators: PINECONE / MODEL / ROUTING / BUILD    |
| `EngineRoom`           | 3-column architecture grid (CORE-01/02/03)             |
| `SkillStore`           | 4 mock skills, category filter bar                     |
| `FeatureLayout`        | Consistent horizontal section structuring + entrance animations |
| `EvervaultCard`        | 21st.dev — Cipher text overlay + radial glow for Engine Room |
| `BackgroundBeams`      | 21st.dev — Dynamic animated background for Hero        |
| `BackgroundPaths`      | 21st.dev — Flowing technical grid for Skill Store      |

### 2.6 Engine Room Cards (CORE-01/02/03)

| Card | Label | Key Specs |
|------|-------|-----------|
| Hybrid Inference Engine | CORE-01 | LiteLLM local ≥8GB VRAM, managed cloud fallback |
| Vector Memory | CORE-02 | Pinecone 1536-dim cosine, per-skill namespacing |
| Atomic Stability | CORE-03 | Docker isolation, BTRFS rollback, Kriya Loop self-annealing |

### 2.7 Terminal Boot Sequence

```
> SYSTEM INITIATED: Euryale Ferox V1.0       [Electric Blue]
> DAEMON: Kriya Loop Active.                  [Terminal Amber]
> TELEMETRY: VRAM 12GB Detected. Routing...  [Green]
> REASONING: Optimizing workflow...           [Light grey]
> STATUS: All systems nominal.               [Electric Blue]
```

After boot, input auto-appears and auto-focuses. User input in `#888`, daemon responses in `#00E5FF`, `● PROCESSING` (amber) during streaming.

---

## 3. JSON Data Schemas

### 3.1 Skill Object — `yantraos/skill/v1`

```json
{
  "$schema": "yantraos/skill/v1",
  "id": "string (uuid-v4)",
  "title": "string",
  "description": "string",
  "version": "string (semver, e.g. '1.2.0')",
  "icon_reference": "string (lucide icon name or absolute path to SVG asset)",
  "tags": ["string"],
  "category": "enum: 'automation' | 'inference' | 'rag' | 'data' | 'system' | 'utility'",
  "execution_environment": {
    "type": "enum: 'local' | 'cloud' | 'hybrid'",
    "requires_vram_gb": "number | null",
    "supported_models": ["string (model slug)"],
    "daemon_hook": "string (Kriya Loop daemon endpoint, e.g. '/api/kriya/execute')"
  },
  "pinecone_metadata": {
    "index_name": "string",
    "namespace": "string",
    "vector_dimensions": 1536
  },
  "author": "string",
  "created_at": "ISO 8601 timestamp",
  "updated_at": "ISO 8601 timestamp",
  "is_public": "boolean",
  "download_count": "number"
}
```

### 3.2 Kriya Loop Telemetry — `yantraos/telemetry/v1`

```json
{
  "$schema": "yantraos/telemetry/v1",
  "timestamp": "ISO 8601 timestamp",
  "daemon_status": "enum: 'BOOTING' | 'ACTIVE' | 'IDLE' | 'ERROR' | 'OFFLINE'",
  "active_model": "string (currently loaded model slug)",
  "cpu_load": {
    "percent": "number (0-100)",
    "core_count": "number"
  },
  "vram_usage": {
    "used_gb": "number",
    "total_gb": "number",
    "percent": "number (0-100)"
  },
  "ram_usage": {
    "used_gb": "number",
    "total_gb": "number",
    "percent": "number (0-100)"
  },
  "inference_routing": "enum: 'LOCAL' | 'CLOUD' | 'FALLBACK'",
  "active_skill_id": "string (uuid-v4) | null",
  "current_cycle": {
    "phase": "enum: 'ANALYZE' | 'PATCH' | 'TEST' | 'UPDATE_ARCHITECTURE' | 'IDLE'",
    "iteration": "number",
    "log_tail": ["string"]
  },
  "pinecone_connection": "enum: 'CONNECTED' | 'DEGRADED' | 'DISCONNECTED'",
  "last_error": "string | null"
}
```

### 3.3 Pinecone Index Schema

| Field              | Type   | Value                              |
|--------------------|--------|------------------------------------|
| Index Name         | string | `yantra-skills`                    |
| Dimensions         | number | `1536` (text-embedding-3-small)    |
| Metric             | string | `cosine`                           |
| Namespace Strategy | string | One namespace per skill slug       |

**Vector Metadata Fields:**

```json
{
  "skill_id": "string",
  "title": "string",
  "category": "string",
  "tags": ["string"],
  "version": "string"
}
```

---

## 4. Arch Linux Daemon Blueprint — The Kriya Loop

### 4.1 What Is the Kriya Loop

The Kriya Loop is YantraOS's **persistent background daemon** — a self-annealing, 4-phase autonomous execution cycle that runs as a `systemd` service on Arch Linux. Derived from the Sanskrit word for "Completed Action," it is a 24/7 worker that never sleeps. It sorts downloads, manages packages, reads logs, and heals the environment while the user rests. It is the core engine that monitors hardware, routes inference, executes Skills, and reports telemetry. It solves the **"Dead OS Crisis"** (Passive Computing Failure where systems experience 30% meta-work and 70% wasted capacity) by transforming the OS from a passive tool into an active, autonomous worker following a continuous `OBSERVATION → ACTION` loop.

### 4.2 The Four Phases

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌────────────────────┐
│ ANALYZE  │ →  │  PATCH   │ →  │   TEST   │ →  │ UPDATE_ARCHITECTURE│
└──────────┘    └──────────┘    └──────────┘    └────────────────────┘
      ↑                                                    │
      └────────────────────────────────────────────────────┘
```

| Phase                | Function                                                        |
|----------------------|-----------------------------------------------------------------|
| `ANALYZE`            | Scan system state (GPU, RAM, disk), evaluate pending skill queue |
| `PATCH`              | Pull updates, apply model weights, adjust routing config        |
| `TEST`               | Validate inference pipeline, run health checks                  |
| `UPDATE_ARCHITECTURE`| Commit state changes, emit telemetry, rotate logs               |

The loop runs with `time.sleep(10)` between iterations to prevent CPU thrashing. Error handling wraps the entire loop so unhandled exceptions log to `/var/log/yantra/engine.log` rather than crashing the daemon.

### 4.3 14-Day Hyper-Sprint Schedule

| Phase | Name | Days | Deliverables |
|-------|------|------|-------------|
| **1** | **The Neural Fabric** | 1–4 | `hardware.py` (VRAM detection), `router.py` (LiteLLM gateway), `memory.py` (ChromaDB RAG), `engine.py` (Kriya Loop orchestrator) |
| **2** | **The Interface** | 5–9 | `shell.py` (Yantra Shell TUI), `theme.tcss` (branding CSS), `widgets.py` (GPUHealth, ThoughtStream), `bridge.py` (UNIX socket IPC) |
| **3** | **The Deployment** | 10–14 | `yantra.service` (systemd), `install.sh` (atomic installer), `50-yantra-snapshot.hook` (BTRFS), `sandbox.py` (Docker), `Dockerfile.agent` |

### 4.4 Daemon Technology Stack

| Component          | Technology       | Purpose                                    |
|--------------------|------------------|--------------------------------------------|
| Language           | Python 3.12+     | Daemon core                                |
| Init System        | `systemd`        | Service management with `Type=notify`      |
| Watchdog           | `sdnotify`       | `WatchdogSec=30s` — heartbeat every 15s, auto-restart on deadlock |
| GPU Telemetry      | `pynvml`         | NVIDIA VRAM/utilization monitoring         |
| GPU Fallback       | `rocm-smi` / `sysfs` / `lspci` | AMD/Intel fallback detection  |
| Local Inference    | Ollama           | Local LLM runner (Llama 3, DeepSeek-R1)   |
| Cloud Inference    | Gemini 2.0 Flash / Claude 3.5 Haiku | Cloud fallback models |
| Inference Router   | `LiteLLM`        | Unified local ↔ cloud model routing with fallback arrays |
| Local Vector Store | `ChromaDB`       | Local embedding cache / offline RAG / Skill Acquisition |
| TUI Framework      | Python `textual` + `rich` | Terminal User Interface         |
| IPC                | UNIX Domain Sockets | `/run/yantra/ipc.sock` — TUI ↔ daemon bridge |
| Containerization   | `docker` + `docker-py` | Skill isolation, ephemeral Alpine containers |
| Snapshot/Rollback  | `btrfs-progs`    | Filesystem snapshots for atomic stability  |
| Pacman Hook        | `50-yantra-snapshot.hook` | Pre-transaction BTRFS snapshot   |

### 4.5 Filesystem Layout

```
/opt/yantra/
├── config.yaml          # API keys (Gemini/Claude) and VRAM thresholds
├── core/
│   ├── __init__.py
│   ├── daemon.py        # Daemon entry point (exec'd by systemd)
│   ├── engine.py        # The Kriya Loop (main daemon orchestrator)
│   ├── hardware.py      # VRAM check → LOCAL_CAPABLE | CLOUD_ONLY
│   ├── hybrid_router.py # LiteLLM routing with fallback arrays
│   ├── sandbox.py       # Red Team hardened Docker sandbox (docker-py)
│   ├── fleet_manager.py # Secure SSH gateway for multi-node Edge telemetry
│   ├── vector_memory.py # ChromaDB RAG implementation
│   ├── ipc_server.py    # UNIX Domain Socket IPC server
│   ├── btrfs_manager.py # BTRFS snapshot/rollback manager
│   ├── installer.py     # Atomic OS Installer pipeline (partitions, BTRFS, GRUB)
│   ├── cloud.py         # Cloud inference backend
│   ├── prompt.py        # LLM prompt engineering
│   └── cli.py           # CLI entry point
├── deploy/
│   ├── systemd/yantra.service  # systemd unit (Type=notify, WatchdogSec=30s)
│   ├── install.sh              # Atomic installer with backup/restore
│   ├── polkit/50-yantra-btrfs.rules  # Polkit BTRFS privilege escalation
│   ├── pacman/00-yantra-autosnap.hook.inactive  # Disarmed BTRFS hook
│   ├── pacman/99-yantra-reload.hook   # Daemon reload on package changes
│   ├── sysusers.d/yantra.conf  # Creates yantra_daemon user at boot
│   └── tmpfiles.d/yantra.conf  # Creates runtime dirs at boot
├── archlive/
│   ├── compile_iso.sh   # Master ISO build script (6 invariants)
│   ├── profiledef.sh    # Archiso profile with file_permissions matrix
│   ├── packages.x86_64  # Package manifest for the ISO
│   └── airootfs/        # Filesystem overlay for the ISO
├── models/              # Downloaded model weights
├── skills/              # Installed skill packages
├── data/                # ChromaDB persistent storage (/var/lib/yantra/chroma)
├── logs/                # Rotating daemon logs (/var/log/yantra/)
├── snapshots/           # BTRFS snapshot metadata
└── requirements.txt     # nvidia-ml-py, litellm, chromadb, psutil, textual, rich, sdnotify, docker
```

### 4.6 Permissions Matrix (Strict)

| Entity            | User              | Group    | Access Scope               |
|-------------------|-------------------|----------|-----------------------------|
| Daemon Process    | `yantra_daemon`   | `yantra` | `/opt/yantra/` (read/write) |
| Skill Executor    | `yantra_daemon`   | `docker` | Docker socket access only   |
| Config Files      | `root`            | `yantra` | `640` (owner rw, group r)   |
| Model Weights     | `yantra_daemon`   | `yantra` | `750` (owner rwx, group rx) |
| Log Directory     | `yantra_daemon`   | `yantra` | `755`                       |
| systemd Unit      | `root`            | `root`   | `/etc/systemd/system/yantra-daemon.service` |
| IPC Socket        | `yantra_daemon`   | `yantra` | `/run/yantra/ipc.sock`      |

> **CRITICAL:** The daemon does NOT run as root. The `yantra_daemon` user is added to the `docker` group for container access. Pacman hooks run under pacman's own context, not the daemon's.

### 4.7 systemd Service Unit

```ini
[Unit]
Description=YantraOS Kriya Loop Daemon — Autonomous System Orchestrator
Documentation=https://yantraos.com/docs
After=network-online.target
Wants=network-online.target
After=local-fs.target
RequiresMountsFor=/run/yantra /var/lib/yantra

[Service]
Type=notify
User=yantra_daemon
Group=yantra
ExecStart=/opt/yantra/venv/bin/python3 /opt/yantra/core/daemon.py
Environment=PYTHONPATH=/opt/yantra
WorkingDirectory=/opt/yantra
EnvironmentFile=-/etc/yantra/secrets.env
WatchdogSec=30s
WatchdogSignal=SIGABRT
Restart=on-failure
RestartSec=5s
StartLimitIntervalSec=300
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=yantra
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/run/yantra /var/lib/yantra
MemoryMax=2G
CPUQuota=200%
TasksMax=64
TimeoutStartSec=90
TimeoutStopSec=30
NotifyAccess=main

[Install]
WantedBy=multi-user.target
```

Key systemd details:

- `Type=notify` — daemon sends `READY=1` via `sdnotify` only after hardware detection, vector memory init, Docker sandbox ping, and IPC socket creation succeed.
- `WatchdogSec=30s` — daemon must send `WATCHDOG=1` every 15 seconds (half-interval best practice); missed heartbeat triggers `SIGABRT` + auto-restart.
- `Restart=on-failure` — restarts only on non-zero exit, signal kill, or watchdog timeout. Does NOT restart on clean exit (graceful SIGTERM).
- `docker.service` removed from `After=` — telemetry boots even if sandbox is degraded. Sandbox gracefully degrades via `SandboxStatus.DEGRADED`.
- `Environment=PYTHONPATH=/opt/yantra` — resolves `ModuleNotFoundError: No module named 'core'` (Milestone 13 fix).
- `EnvironmentFile=-/etc/yantra/secrets.env` — loads API keys; `-` prefix means non-fatal if missing.
- Security hardening: `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, explicit `ReadWritePaths`.

### 4.8 Inference Routing Decision Tree

```
hardware.py → detect VRAM:
  IF pynvml detects NVIDIA RTX / AMD Radeon with RAM >= 16GB:
    capability = LOCAL_CAPABLE (Path A - 100% Air-gapped privacy)
    primary_model = "ollama/llama3" or "deepseek-r1" (http://localhost:11434)
  ELIF rocm-smi/sysfs detects AMD/Intel or RAM < 8GB:
    capability = CLOUD_ONLY (Path B - Mass market accessibility)
  ELSE (no GPU / detection fails):
    capability = CLOUD_ONLY

router.py → LiteLLM Router (Orchestration & Normalization):
  IF LOCAL_CAPABLE:
    route → Ollama local
    fallback → gemini/gemini-2.5-flash (on APIConnectionError or timeout)
  IF CLOUD_ONLY:
    route → gemini/gemini-2.5-flash
    fallback → claude/claude-3.5-haiku

Kriya Loop guarantees: inference NEVER hangs. All paths have fallbacks via a Secure API Gateway.
```

### 4.9 Skill Acquisition via RAG (ChromaDB)

When the daemon determines a successful sequence of commands:

1. Store the execution path as an embedding in ChromaDB at `/var/lib/yantra/chroma` (Vector Memory for execution logs and workflows).
2. Before generating new code, query the vector store for semantic similarity.
3. If high-similarity match found → retrieve verified past solutions to solve current problems (Contextual Awareness).
4. This creates permanent skill retention — **One-Shot Learning**: Teach Yantra a task once (e.g., 'Deploy React App'), and it remembers the steps forever. The system **learns from its environment**.

### 4.10 Yantra Shell TUI (Terminal User Interface)

**Three-Pane Layout:**

| Pane | Position | Width | Content |
|------|----------|-------|---------|
| Telemetry Grid | Left | 30% | Real-time VRAM bars, CPU metrics, Kriya Loop state (Sleeping/Monitoring/Optimizing/Executing) |
| Audit Log | Right | 70% | Auto-scrolling `RichLog` — step-by-step reasoning, bash commands, execution logs |
| Interaction Prompt | Bottom | 100% | Single-line input for natural language directives |

**Key Features:**

- `GPUHealth` widget: Reactive, polls hardware every 2 seconds via `hardware.py` (falls back to mock 16GB RTX 4090 on Windows/non-CUDA), displays VRAM % and active Kriya Phase.
- `ThoughtStream` widget: Displays raw LLM reasoning and daemon logs.
- Mode toggle: `M` key switches between **Manual Mode** (user commands) and **Autonomous Mode** (AI watches logs)
- Emergency halt: `Ctrl+C` invokes immediate task stop
- IPC Bridge (`bridge.py`): Automatically detects OS. Uses **TCP `127.0.0.1:50000` on Windows** and **UNIX Domain Sockets (`/tmp/yantra.sock`) on Linux**. TUI serializes intents as JSON, daemon streams responses back in real-time.
- UI Styling: Enforces **strict hex color format** (`[#00E5FF]`, `[#888888]`, `[#FFB000]`) instead of custom Rich tags to prevent `MissingStyle` exceptions in Textual 0.52+.
- TUI does NOT block the daemon thread — asynchronous architecture via `asyncio`

### 4.11 Docker Sandboxed Execution (Red Team Hardened v1.2)

When the inference engine generates code to execute:

1. Script payload undergoes **static input validation**: type assertion, 64 KiB size cap, NUL byte stripping, image allowlist check, environment variable sanitization, shell binary allowlisting.
2. Spins up ephemeral Alpine Linux container via `docker-py` (`core/sandbox.py`).
3. Container runs with the following **non-negotiable security matrix**:
   - `network_mode="none"` — zero network access (prevents exfiltration)
   - `mem_limit="512m"` — OOM-killed at 512 MiB
   - `cpu_quota=50000` — 50% of one CPU core maximum
   - `pids_limit=64` — fork bomb protection
   - `read_only=True` — immutable root filesystem
   - `cap_drop=["ALL"]` — zero Linux capabilities
   - `security_opt=["no-new-privileges:true"]` — blocks setuid/setgid escalation
   - `auto_remove=True` — container destroyed immediately after exit
   - `tmpfs /tmp: size=64m, noexec, nosuid` — capped writable scratch
   - `user="nobody"` — runs as UID 65534 (nobody)
   - `privileged=False` — explicit denial (defense-in-depth)
4. **Prohibition by Omission**: `volumes`, `binds`, `privileged`, `cap_add`, `pid_mode`, `ipc_mode`, `devices` parameters are **structurally absent** from the `execute()` method signature. No caller — including an LLM generating function calls — can inject them.
5. **Image Allowlist**: Only `alpine:3.19`, `alpine:3.20`, `alpine:latest`, `yantra-agent:latest` are permitted. All other images rejected with `VALIDATION_ERROR`.
6. **Immutable Results**: `SandboxResult` is a frozen dataclass — post-creation mutation is impossible, preserving forensic integrity.
7. **Audit Trail**: Every execution logged with SHA-256 script fingerprint, resolved image, and outcome.
8. **Graceful Degradation**: If Docker is offline, sandbox enters `DEGRADED` state. Kriya Loop continues in observe-only mode. No crash.
9. Only `stdout` and return codes piped back to Kriya Loop.

### 4.12 BTRFS Atomic Rollback

Before any high-stakes system command (e.g., `pacman -Syu`):

1. `50-yantra-snapshot.hook` fires on `Operation = Upgrade, Install, Remove`
2. Hook executes `btrfs subvolume snapshot` to clone `/@` → `/@snapshots/yantra_pre_exec_<timestamp>`
3. Snapshots older than 7 days are auto-pruned
4. On catastrophic failure: edit GRUB boot parameter → `rootflags=subvol=@snapshots/yantra_pre_exec_...` → system boots into stable snapshot
5. **Zero-risk operational autonomy**

### 4.13 Atomic Installer (`install.sh`) Requirements

1. Check for and install: `python-pip`, `docker`, `cuda`, `python-pynvml` via `pacman --noconfirm`
2. Create `yantra_daemon` user — do NOT run daemon as root
3. Add `yantra_daemon` to `docker` group
4. Before installing new files: backup `/opt/yantra` → `/var/backups/yantra_$(date).tar.gz`
5. If Python requirements fail → RESTORE backup immediately and exit
6. The installer itself must be **atomic** — partial installations must be rolled back

### 4.14 Required Arch Linux Packages

```
linux-headers, nvidia-dkms, cuda, python-pip, docker, docker-compose,
python-pynvml (AUR), chromadb (pip), litellm (pip), textual (pip),
rich (pip), sdnotify (pip), docker-py (pip), psutil (pip)
```

---

## 5. Component Architecture Matrix

Source: `YantraOS High-Tech Architectural and Development Specification.xlsx`

| Component | Logic Pathway | Hardware Req | Tech Stack | Purpose | Phase | Security |
|-----------|---------------|-------------|------------|---------|-------|----------|
| Hybrid Inference Engine | VRAM Check (Local >8GB / Cloud <8GB) | NVIDIA RTX GPU (8GB+) | LiteLLM, pynvml, Ollama, Gemini API | Autonomous task routing local ↔ cloud | 1 (Days 1-4) | Hardware fallback + LiteLLM redundancy |
| Kriya Loop (Daemon) | Local exec via Docker / Cloud Fallback | Arch Linux env | Python 3.12, systemd, asyncio | 24/7 background optimization & healing | 1 & 3 | systemd WatchdogSec, Type=notify, non-root |
| Yantra Shell (TUI) | User interaction & telemetry display | Terminal + Nerd Font | textual, Rich, UNIX Domain Sockets | Futuristic HUD for monitoring & commands | 2 (Days 5-9) | Async IPC isolated from daemon memory |
| Vector Memory (RAG) | Semantic search before raw inference | Persistent storage | ChromaDB | Skill acquisition via stored execution paths | 1 (Day 4) | Local vector store (privacy-focused) |
| Sandboxed Execution | AI-generated code execution | Docker Engine | Docker (Alpine), docker-py | Safe execution in isolated containers | 3 (Day 10) | Red Team hardened: frozen image allowlist, input sanitization, `cap_drop=ALL`, `network_mode=none`, `pids_limit=64`, `user=nobody`, `no-new-privileges`, structural prohibition of volumes/binds |
| Atomic Rollback System | Pre-transaction pacman hook | BTRFS file system | Pacman Hooks, BTRFS Snapshots | Auto-snapshot before OS modifications | 3 (Day 11) | `50-yantra-snapshot.hook` (atomic backups) |

---

## 6. Telemetry Emission

The daemon emits `yantraos/telemetry/v1` JSON (see §3.2) via:

- **WebSocket** push to connected Web HUD instances
- **HTTP POST** to `/api/telemetry/ingest` on the Vercel backend
- **UNIX Domain Socket** to the local Yantra Shell TUI
- **journalctl** structured logging for local `systemd` integration

---

## 7. Development Toolchain ("God-Mode")

| Tool | Role | Target Phase |
|------|------|-------------|
| **Antigravity IDE** (Gemini 3 Pro) | Agentic backend code generation — Python daemons, hardware abstraction, Kriya Loop | Phase 1 |
| **Google Stitch** | Wireframe → TUI code conversion (textual + Rich) | Phase 2 |
| **Gemini 3 Pro** | High-level architectural reasoning, routing permutations, config arrays | Phase 1 |
| **Claude Opus 4.6** | Security auditor / Red Team engine — deployment scripts, container escapes, privilege escalation | Phase 3 |
| **Perplexity Pro** | Real-time Arch Linux driver anomalies, hardware error codes, systemd faults | All phases |

---

## 8. Build Constraints & Known Issues

| ID    | Constraint                                              | Impact  | Status   |
|-------|---------------------------------------------------------|---------|----------|
| C-001 | npm package name cannot contain `.` → workspace `YantraOS.com` blocked `create-next-app` | Medium | ✅ Resolved |
| C-002 | Next.js 14 requires Node.js 18.17+                     | Low     | ✅ Met   |
| C-003 | Framer Motion v11 SSR hydration caveats — terminal animations must use `"use client"` | Medium | ✅ Handled |
| C-004 | Geometric Law enforced in `tailwind.config.ts` — all `borderRadius` → `0px` | N/A | ✅ Enforced |
| C-005 | `postcss.config.mjs` had CommonJS `module.exports` in ESM — switched to `export default` | Low | ✅ Fixed |
| C-006 | OpenAI `gpt-4o-mini` rate-limited → pivoted to `google("gemini-2.0-flash")` | High | ✅ Resolved |
| C-007 | 90% of global users excluded from local AI by expensive GPU requirements → solved by Hybrid Engine | High | ✅ Architected |
| C-008 | LLM-generated code could execute destructive commands on host → solved by Docker sandbox | Critical | ✅ Architected |

---

## 9. Repository & Deployment Summary

| Property        | Value                                          |
|-----------------|------------------------------------------------|
| GitHub Org      | `osyantra`                                     |
| Repo            | `yantraos-web-hud` (private)                   |
| Branch          | `main`                                         |
| Hosting         | Vercel                                         |
| Production URL  | `https://yantraos.com`                         |
| Static Export   | `build-hostinger.ps1` (removes API routes)     |
| Package Name    | `yantra-os`                                    |
| Current Version | `0.1.0`                                        |

---

## 10. Phase Status Matrix

| Phase | Name               | Status      | Deliverables                                   |
|-------|--------------------|---------    |------------------------------------------------|
| 0     | Engine Init        | ✅ COMPLETE | Core docs, Next.js scaffold, JSON schemas      |
| 1     | Blueprint          | ✅ COMPLETE | Data schemas locked, architecture defined       |
| 2     | Link               | ✅ COMPLETE | Pinecone client, health endpoint, env config    |
| 3     | Architect          | ✅ COMPLETE | `/api/kriya/execute`, `/api/skills/search`      |
| 4     | Stylize            | ✅ COMPLETE | Full UI: NavBar, Terminal, Engine Room, Skills   |
| 5     | Trigger            | ✅ COMPLETE | Vercel deployed, GitHub synced, live at production URL |
| 6-9   | RAG + Fixes        | ✅ COMPLETE | NotebookLM sync, Hero UI fix, Vertex AI pivot  |
| **10**| **Windows Sim**    | ✅ COMPLETE | **Daemon Windows simulation, HUD Telemetry poll, IPC TCP fix** |
| 11    | Daemon Build       | ✅ COMPLETE | Arch Linux Kriya Loop daemon — 14-Day Hyper-Sprint |
| 12    | ArchISO Build      | ✅ COMPLETE | Archlive generation: Disarmed hooks, mkarchiso workarounds, CRLF updates |
| 13    | Native Validation  | ✅ COMPLETE | QEMU native testing, atomic installer (`install.sh`), systemd fixes |
| **14**| **Gold Master v1.2** | ✅ COMPLETE | **Sandbox Red Team hardening, compile_iso.sh 6-invariant rewrite, build.sh prep script, docker.service decoupling** |
| **15**| **Phase 2 Alpha / RC4** | ✅ COMPLETE | **Fleet Manager async SSH, Pure TUI (Wayland purged), ISO Verification, BTRFS Polkit integration, UFW lockdown** |

---

## 11. Source Documents Index

| # | Document | Type | Content |
|---|----------|------|---------|
| 1 | `INITIATING ARCHITECTURAL PROTOCOL.docx` | TEP | 3-Phase Hyper-Sprint blueprint with "God-Prompts" for each phase |
| 2 | `YantraOS_ AI OS Development Plan.docx` | Full Spec | 36K-char exhaustive spec — philosophy, hardware profiling, LiteLLM routing, ChromaDB, TUI, IPC, systemd, BTRFS, Docker, security audit |
| 3 | `YantraOS High-Tech Architectural Specification.xlsx` | Matrix | 6-component architecture matrix with tech stack, phases, and security protocols |
| 4 | `YantraOS_Protocol.pdf` | Protocol | YantraOS protocol documentation (24.6 MB) |
| 5 | `YantraOS_The_Architecture_of_Autonomy.pdf` | Architecture | Full architecture of autonomy reference (32.1 MB) |
| 6 | `custom_os_linux_kernel_guide.txt` | Guide | Complete Linux kernel OS build guide (LFS, toolchain, bootloader) |
| 7 | `yantra_core.md` | Constitution | Project constitution — aesthetic law, JSON schemas, stack |
| 8 | `yantra_plan.md` | Sprint Plan | Sprint phases & routing checklist |
| 9 | `yantra_telemetry.md` | Telemetry | Integration discovery & constraints log |
| 10 | `yantra_kriya.md` | Execution Log | Build log & error traces |

---

## 12. Post-MVP Roadmap & Market Strategy

**Market Strategy:**

- **Primary:** Open Source Enthusiasts & Arch Linux Users.
- **Secondary:** STEM Students in hardware-constrained regions (Emerging Markets).
- **Differentiation:** The only OS optimized for Hybrid AI out of the box.

**Timeline (Road to Autonomy):**

1. **PHASE 1 (MVP) — The Neural Fabric & Interface**: Yantra Shell. Overlay for existing Linux distros. (Current Focus)
2. **PHASE 2 (ALPHA) — The Deployment**: Standalone ISO release. Integrated Hybrid Inference. Seeking funding to finalize.
3. **PHASE 3 (ECOSYSTEM) — The Future**: Yantra Skill Store. A public marketplace for users to package, publish, and monetize shareable RAG workflows, creating a Network Effect where collective intelligence improves every machine.
4. **Future Support**: Multi-GPU routing and ARM architecture builds.

---

## 13. Milestone 6: ISO Build & Native Validation Updates

1. **Build Engineering (`compile_iso.sh`)**:
   - Patched to copy `.inactive` pacman hooks (specifically `00-yantra-autosnap.hook.inactive`) to prevent premature BTRFS execution inside the chroot environment.
   - Preserves virtual environment hashbang correction logic for `/opt/yantra/venv/bin/*`.
2. **mkarchiso Fixes**:
   - Updated `profiledef.sh` with modern boot modes (`bios.syslinux` and `uefi.grub`).
   - Overrode `airootfs/etc/passwd` to sanitize users and avoid an unbound array fatal error in mkarchiso's `customize_airootfs.sh` skeleton copy loop.
   - Replaced Windows CRLF line endings with Unix LF globally in configurations and scripts.
3. **Atomic Deployment (`install.sh`)**:
   - Developed a robust bare-metal installer script with `trap rollback ERR` functionality referencing `/var/backups`.
   - Automatically reinstates the `.inactive` pacman hooks post-installation.
   - Ensures `yantra_daemon` group membership and docker integrations.
4. **Systemd Daemon Patch**:
   - `deploy/systemd/yantra.service` was updated with `Environment=PYTHONPATH=/opt/yantra` to resolve a namespace dislocation (`ModuleNotFoundError: No module named 'core'`) during native QEMU bootstrap.

---

## 15. Core Infra, ISO Build, and Kiosk Fixes (Feb-Mar 2026)

1. **Async Vector Memory Integrity (`core/vector_memory.py`)**:
   - Fixed the `RuntimeWarning: coroutine 'VectorMemory.initialize' was never awaited` bug.
   - Refactored `_require_initialized()` from a synchronous check to an `async def` that dynamically awaits `self.initialize()` if not previously initialized.
   - Inserted `await` to all internal call sites in `VectorMemory` that trigger storage (`store_execution`, `index_skill`) or queries (`query_executions`, `query_skills`).
   - Hardened `VectorMemory` with an `_init_failed` flag to gracefully degrade the system—logging a single warning and preventing infinite retry loops if `chromadb` fails to load.

2. **Telemetry Payload Re-arming (`core/cloud.py`)**:
   - Re-enabled Bearer token authentication in `emit_telemetry()` by uncommenting the `Authorization` header block, directly referencing `os.environ.get('YANTRA_TELEMETRY_TOKEN')`.
   - Verified strict trailing slash enforcement on the payload URL (`https://www.yantraos.com/api/telemetry/ingest/`).

3. **Secrets Alignment & Host Injection (`hybrid_router.py`, `compile_iso.sh`, `yantra.service`)**:
   - Fully transitioned ISO build structure and daemon services configuration to map to `host_secrets.env` (formerly `secrets.env`).
   - Updated `archlive/compile_iso.sh` to stage `host_secrets.env` directly into `/etc/yantra/host_secrets.env` inside the `airootfs` (permissions: 0400/0600).
   - Reloaded all environments in systemd files (`deploy/systemd/yantra.service` and `archlive/airootfs/etc/systemd/system/yantra.service`) using the path `EnvironmentFile=-/etc/yantra/host_secrets.env`.
   - Explicitly mapped `SECRETS_ENV_PATH = "/etc/yantra/host_secrets.env"` in `core/hybrid_router.py` to target the host's payload filepath natively.

4. **ArchISO Build Hardening (`compile_iso.sh`)**:
   - Redirected `mkarchiso` working directory from `/tmp/archiso-tmp` (tmpfs) to physical disk (`work/`) to resolve "No space left on device" errors caused by Wayland/NVIDIA packages expanding airootfs beyond RAM limits.
   - Hardened `pip install` commands with `--retries 10 --timeout 120` to survive flaky PyPI connections during ISO builds, ensuring large packages like `chromadb` successfully install.
   - Dynamically injected `["/root/.automated_script.sh"]="0:0:0755"` into `profiledef.sh` via Phase 4 to resolve boot script execution permissions.

5. **Yantra User & Cage Wayland Initialization**:
   - Added `yantra_user` (UID 1000) directly to `airootfs/etc/passwd` and created the `yantra_user` group (GID 1000) in `airootfs/etc/group`. Added structural group memberships (`video`, `render`) for GPU access.
   - Introduced Phase 3.6b in `compile_iso.sh` to explicitly `install -dm700` the `/home/yantra_user` directory, resolving "No such file or directory" during live session login.
   - Bound `XDG_RUNTIME_DIR=/run/user/1000` to the Cage kiosk execution command and pre-created the runtime directory prior to invoking `su - yantra_user`. This eliminates the `DQUANTUM_ID` authentication error.

---

## 16. Milestone 7: Pure TUI v0.3.0 & Sandbox Fallback Execution (March 2026)

1. **Wayland Purge & Pure TUI Architecture**:
   - Eliminated `cage`, `sway`, `alacritty`, `grim`, `slurp`, and `wl-clipboard` from `archlive/packages.x86_64`.
   - Stripped all `wayland` initialization logic out of `archlive/compile_iso.sh` boot script.
   - Live ISO now boots directly into `tty1` running the Textual-based `core/tui_shell.py` via `yantra_user`.

2. **TUI Interactive Command Router (IPC Bridge)**:
   - Built a custom `Input` widget command bar at the bottom of the TUI tracking: `pause_loop`, `resume_loop`, `inject <cmd>`.
   - **Pause/Resume**: Commands are serialized as `{"action": "pause_loop"}` / `{"action": "resume_loop"}` over the `/run/yantra/ipc.sock` socket. 
   - Engine (`core/engine.py`) reads `self._state.is_paused` and effectively idles the `_phase_sense` loop when paused to grant the operator manual oversight.

3. **Injected Command Sandbox Fallback Execution**:
   - `core/engine.py` re-engineered `_phase_act` to grant operator `injected_command` actions a dedicated, two-stage execution cascade:
   - **Stage 1 (Isolated)**: Attempt execution via `sandbox.execute(script)` (Alpine container).
   - **Stage 2 (Host Fallback)**: If sandbox is `DEGRADED` (e.g., Docker daemon offline on live boot) or throws an exception, engine gracefully falls back to direct `asyncio.create_subprocess_shell` execution on the Arch host with a 30s timeout.
   - Autonomous LLM actions remain strictly bound to Stage 1. They are structurally denied host fallback to preserve the security boundary.

4. **SSE ThoughtStream Broadcast Extension**:
   - Both Stage 1 (Sandbox) and Stage 2 (Host) execution paths now actively pipe `stdout` (truncated to 2000 chars) and `stderr` (truncated to 1000 chars) back through the `push_log_event()` SSE stream.
   - Ensures deep visibility for the operator: what happens in the engine natively reflects in the TUI HUD in real-time.

5. **Boot Sequence Stabilization**:
   - Explicitly injected `systemctl start docker` into the `compile_iso.sh` generation of `.automated_script.sh` just before starting `yantra.service`.
   - Corrected heredoc `if`/`fi` bash syntax in the TTY1 boot execution logic preventing crashes.

---

## 17. Milestone 8: Live ISO Bare-Metal Hardening (RC5–RC7) (March 2026)

1. **State Cleansing & Amnesia Protocol (`compile_iso.sh`)**:
   - Prevented the host's Kriya Loop iteration state from bleeding into the ISO by injecting commands to purge `*.json` state trackers and `__pycache__` artifacts from `/opt/yantra/` during the staging phase.
   - Cleansed legacy ChromaDB vector fragments by aggressively wiping `/var/lib/yantra/chromadb` and `core/chromadb` from the build overlay.

2. **Cryptographic Sanitization (`compile_iso.sh`)**:
   - Resolved the `Vertex_ai_betaException` systemd load failure by explicitly targeting `host_secrets.env` inside the `airootfs` with `sed` strips, removing all single quotes `'`, double quotes `"`, and trailing spaces inserted by shell variable expansion.
   - Inserted a robust pre-flight check failing the ISO compile if `GEMINI_API_KEY` is missing.

3. **Daemon Deep Runtime Scan (`core/engine.py` & `yantra.service`)**:
   - Aligned `WATCHDOG_SEC = 30` in Python to match `WatchdogSec=30s` in systemd (previously mismatched at 15s).
   - Confirmed `READY=1` sdnotify signaling logic completes correctly for `Type=notify`. All critical execution and inference phases assert safe exception trapping.

4. **Docker VFS Injection (Sandbox Stability)**:
   - Fixed a fatal Docker daemon crash caused by attempting to nest the `overlay2` storage driver inside Archiso's root `overlayfs`.
   - Injected `/etc/docker/daemon.json` into the `airootfs` forcing the fallback `"storage-driver": "vfs"`. This sacrifices I/O speed but guarantees sandbox isolation survives a Live USB environment.

5. **Definitive Bootloader Persistence Anchor**:
   - Enforced permanent physical partition mounting for Yantra's RAG databases by targeting `cow_label=yantra_cow cow_spacesize=8G`.
   - Executed a global patch across all *9* bootloader configurations: `grub.cfg`, `loopback.cfg`, `archiso_sys-linux.cfg`, `archiso_pxe-linux.cfg`, `01-archiso-linux.conf`, and `02-archiso-speech-linux.conf`—ensuring total resilience regardless of BIOS/UEFI firmware routing.

6. **Bare-Metal NVIDIA GPU Acceleration**:
   - Hardcoded `nvidia` and `nvidia-settings` directly into the `packages.x86_64` manifest for `mkarchiso` to pull the proprietary matrix.
   - Activated the **Nouveau Killswitch**: Appended `nouveau.modeset=0 nvidia-drm.modeset=1` to all *11* kernel execution boot lines to mathematically eliminate open-source driver conflicts.
   - Wrote `airootfs/etc/mkinitcpio.conf` specifying `MODULES=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)` to assure early-boot KMS initialization before any console or shell instantiation.

## 18. Milestone 9: Phase 2 Alpha & RC4 Gold Master (March 2026)

1. **Multi-Node Edge Topology (`core/fleet_manager.py`)**:
   - Implemented a secure async SSH gateway module for fleet management.
   - Authorized execution of telemetry commands (e.g., `htop`, `df -h`) on remote nodes listed in `/opt/yantra/config/nodes.json`.

2. **Ephemeral Sandbox Hardening (`core/sandbox.py`)**:
   - Elevated resource constraints: `mem_limit="512m"` to prevent premature OOMs during heavy tasks.
   - Enforced maximum privilege isolation by executing containers as `user="nobody"` (UID 65534).
   - Solidified Prohibition by Omission by strictly omitting `volumes`, `privileged`, and other dangerous Docker kwargs.
   - Image allowed list locked to `alpine:3.19/3.20/latest` and `yantra-agent:latest`.

3. **Pure TUI & ISO Consolidation (`archlive/compile_iso.sh`)**:
   - Transitioned from `nmtui` and Wayland reliance to a pure headless/TUI boot.
   - Integrated `getty@tty1` override to auto-login `yantra_user` directly into the TUI.
   - Replaced NetworkManager dependency with a lightweight `iwd` stack.

4. **Security & Validation Hooks**:
   - **UFW Baseline**: Enforced default `DROP` for incoming traffic (`airootfs/etc/ufw/ufw.conf`).
   - **Polkit Isolation**: Bound `pkexec btrfs` execution purely to the `yantra_daemon` user (`/etc/polkit-1/rules.d/50-yantra-btrfs.rules`), preventing unauthorized snapshot management.
   - **ISO Verification**: Built `archlive/build_verify.sh` for cryptographic validation (`sha256sum`) and payload auditing (`bsdtar`) prior to distribution.

5. **Kriya Loop Complete Audit (`core/engine.py`)**:
   - Fully traced and validated the `SENSE → REASON → ACT → REMEMBER` pipeline.
   - Confirmed deterministic LLM route fallbacks in `hybrid_router.py`.
   - Closed the feedback loop: stdout/stderr from `sandbox.py` is accurately channeled back into the LLM context (`last_action_results`) for subsequent iterations.

---

> **EOF** — This document is the single source of truth for all YantraOS context. Any future agent session MUST read this file first before any implementation work.
