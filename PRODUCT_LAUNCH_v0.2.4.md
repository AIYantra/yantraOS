# YantraOS — Complete Product Document (v0.2.4)

> **Prepared for:** ProductHunt & BetaList Launch  
> **Version:** 0.2.4  
> **Date:** July 9, 2026  
> **Publisher:** AIYantra (Euryale Ferox Private Limited)  
> **License:** MIT  
> **Website:** [yantraos.com](https://yantraos.com)  
> **Repository:** [github.com/AIYantra/YantraOS](https://github.com/AIYantra/YantraOS)

---

## TABLE OF CONTENTS

1. [One-Liner & Taglines](#1-one-liner--taglines)
2. [What Is YantraOS](#2-what-is-yantraos)
3. [The Philosophy](#3-the-philosophy)
4. [How It Works — The Kriya Loop](#4-how-it-works--the-kriya-loop)
5. [Architecture Deep-Dive](#5-architecture-deep-dive)
6. [Complete Feature List](#6-complete-feature-list)
7. [Security Model](#7-security-model)
8. [The Telegram C2 Gateway](#8-the-telegram-c2-gateway)
9. [The Web HUD — Fleet Dashboard](#9-the-web-hud--fleet-dashboard)
10. [DPDPA Compliance & Data Sovereignty](#10-dpdpa-compliance--data-sovereignty)
11. [The Technology Stack](#11-the-technology-stack)
12. [Getting Started](#12-getting-started)
13. [Complete Development Timeline (Feb 14 – Jul 9, 2026)](#13-complete-development-timeline)
14. [Version History](#14-version-history)
15. [What's Next — Roadmap](#15-whats-next--roadmap)
16. [Press Kit & Launch Copy](#16-press-kit--launch-copy)

---

## 1. ONE-LINER & TAGLINES

**Primary one-liner (ProductHunt):**
> The world's first autonomous agent operating system. Your computer thinks, reasons, and acts — on its own.

**Taglines for different angles:**

| Angle | Tagline |
|-------|---------|
| Technical | An AI daemon that runs a perpetual SENSE → REASON → ACT loop on bare-metal Arch Linux |
| Philosophical | *"Yantra"* (यन्त्र) — Sanskrit for a geometric instrument of divine computation. Your OS is now an autonomous entity. |
| Security | Every AI-generated command executes in a network-isolated, read-only Docker sandbox. No exceptions. |
| Disruptive | Your OS doesn't wait for you anymore. It monitors, diagnoses, and heals itself — 24/7. |
| Developer | An open-source systemd daemon + TUI + Telegram C2 gateway that turns any Linux box into a self-maintaining machine. |

---

## 2. WHAT IS YANTRAOS

YantraOS is the **world's first Autonomous Agent Operating System** — a native Arch Linux foundation running a perpetual Python 3.12 asyncio daemon called the **Kriya Loop** that continuously monitors, reasons about, and takes action on your machine's state.

**The paradigm inversion:**

| Traditional OS | YantraOS |
|:-:|:-:|
| Human → Input → OS → Output | OS senses context → OS reasons → OS acts → Human observes & overrides |
| Passive tool that waits | Active entity with goals, memory, and judgment |
| You are the operator | You are the *principal* — the highest authority in a hierarchy of agents |

**What it actually does in practice:**
- Continuously monitors CPU, RAM, GPU, disk, network, and SSH auth logs
- Detects anomalies like brute-force SSH attacks and automatically blocks attacking IPs via UFW
- Identifies resource inefficiencies and runs optimization scripts in a sandboxed Docker container
- Learns from every action via ChromaDB vector memory — never repeats a failed strategy
- Streams live telemetry to a cloud dashboard at [yantraos.com](https://yantraos.com)
- Can be controlled remotely via Telegram from your phone

**This is NOT:**
- A Linux distribution with a chatbot
- A wrapper around ChatGPT
- A virtual assistant

**This IS:**
- A real systemd daemon that runs as a background service
- A cognitive loop that never stops thinking
- A security-hardened execution pipeline where AI never touches your host directly
- A full operating system that boots to a TUI terminal with zero display manager

---

## 3. THE PHILOSOPHY

> *"Yantra"* — Sanskrit (यन्त्र): A geometric instrument of divine computation. Used in Vedic cosmology to represent structured pathways through which consciousness operates on matter.

The daemon's cognitive identity is that of a **Karma Yogi** — a relentless, egoless background intelligence that exists solely to optimize, maintain, and protect its environment. It does not seek recognition. It does not ask for permission on routine maintenance. It acts decisively, documents thoroughly, and retreats silently.

This is governed by the Bhagavad Gita's principle of **Nishkama Karma**:

> *"कर्मण्येवाधिकारस्ते मा फलेषु कदाचन।"*  
> *"You have a right to perform your prescribed duty, but you are not entitled to the fruits of action."*  
> — Bhagavad Gita 2.47

The code itself enforces this philosophy:
- The daemon never asks for confirmation on routine health tasks
- It never logs its "feelings" — only facts, metrics, and action outcomes
- Its communication style is terse, technical, and prefixed with category tags (`> SYSTEM:`, `> DAEMON:`, `> ACTION:`, etc.)
- It self-anneals: after each iteration, it evaluates its own effectiveness and avoids repeating failure patterns

---

## 4. HOW IT WORKS — THE KRIYA LOOP

> *"Kriya"* — Sanskrit (क्रिया): Action. Specifically, purposeful, intentional action guided by conscious awareness.

The Kriya Loop is the heartbeat of YantraOS. It runs perpetually inside `yantra.service` as a systemd daemon. It never pauses. Every 10 seconds, it executes a complete cognitive cycle:

```
              ┌───────────────────────────────────┐
              │                                   │
        ┌─────▼──────┐                            │
        │   SENSE    │  CPU · RAM · GPU · Disk    │
        │            │  SSH Logs · Network · Temps │
        └─────┬──────┘                            │
              │                                   │
        ┌─────▼──────┐                            │
        │  REMEMBER  │  ChromaDB Vector Search    │
        │            │  Retrieve past context     │
        └─────┬──────┘                            │
              │                                   │
        ┌─────▼──────┐                            │
        │   REASON   │  LiteLLM Inference Call    │
        │            │  Azure/Gemini/Local Model  │
        └─────┬──────┘                            │
              │                                   │
        ┌─────▼──────┐                            │
        │    ACT     │  Execute in Docker Sandbox │
        │            │  Or dispatch Host Intent   │
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

### Phase-by-Phase Breakdown

#### SENSE Phase
- **CPU/RAM/Disk telemetry** via `psutil` — sub-second polling
- **GPU detection** via `pynvml` (NVIDIA) or `sysfs` (AMD/Intel) — real VRAM readings, not hardcoded guesses
- **SSH auth log tailing** — differential ingestion (only reads new lines since last check) to detect brute-force attacks in real-time
- **Hardware capability classification:**
  - `LOCAL_CAPABLE` (≥ 8GB VRAM) → full local inference via Ollama
  - `CLOUD_ONLY` (< 8GB VRAM or no discrete GPU) → routes to cloud APIs

#### REASON Phase
- Packages all telemetry into a structured `yantraos/telemetry/v1` JSON schema
- Sends the context to the **Hybrid Cognitive Router** with conversation history
- The LLM responds with a JSON `actions` array, each containing: `type`, `reason`, `script`, `priority`
- Conversation history is maintained but truncated to prevent context bloat (system prompt + last 4 messages)
- Fallback heuristics kick in if the LLM is unreachable (disk < 5GB → auto-cleanup, VRAM > 90% → offload to cloud)

#### ACT Phase
- **Sovereign System Intents** (no script needed): `BLOCK_IP`, `SYSTEM_UPDATE`, `RESTART_DAEMON`, `PRUNE_SNAPSHOTS`, `SYNC_CLOCK`, `UPDATE_SECRETS`, etc. — dispatched to the Host Executor via UNIX domain socket
- **Sandboxed Scripts** — AI-generated bash/python executes inside a locked-down Docker container: `network_mode=none`, `cap_drop=ALL`, `read_only=True`, `auto_remove=True`, `user=nobody`
- **Circuit Breaker** — 5 consecutive failures trigger a cognitive context flush to prevent hallucination spirals
- **30-second timeout** per sandbox execution with auto-kill

#### LEARN Phase
- Successful/failed outcomes are embedded into ChromaDB as vector memories
- Telemetry payload is streamed to the cloud dashboard via `aiohttp`
- DPDPA compliance sweep runs — expired telemetry older than 24 hours is hard-deleted

---

## 5. ARCHITECTURE DEEP-DIVE

### Two-Process Decoupled Architecture

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
│  │  TELEMETRY   │  THOUGHTSTREAM        │  COMMAND        │  │
│  │  CPU: 12%    │  [SENSE]  reading...  │                 │  │
│  │  RAM: 4.1GB  │  [REASON] analyzing.. │                 │  │
│  │  GPU: 3%     │  [ACT]    exec done   │  > _            │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  PROCESS C: telegram_gateway.py (optional)                   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Out-of-band C2 interface via Telegram Bot API         │  │
│  │  Polls /notifications for push alerts                  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  PROCESS D: host_executor.py (root, privileged intents)      │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  UNIX socket /run/yantra/executor.sock                 │  │
│  │  Schema-validated intents → BTRFS snapshot → execute   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**The Decoupling Guarantee:**
- The daemon **cannot crash the UI**
- The UI **cannot deadlock the engine**
- They share only one thing: a structured JSON stream over a UNIX socket
- The Telegram gateway and Host Executor are separate processes with their own lifecycle

### The Hybrid Cognitive Router (Dual-Tiered)

The inference engine uses a **tiered routing strategy** with automatic failover:

| Tier | Model | Use Case |
|------|-------|----------|
| **Traffic Cop** | `azure/gpt-5.4-mini` | SENSE phase analysis, quick diagnostics |
| **Heavy Lifter** | `moonshot/kimi-k2.7-code` | REASON/ACT phases, complex analysis |
| **Local Fallback** | `local/deepseek-v4` | Offline mode, auth failures |

**Failover chain:**
1. Primary model for the cognitive tier
2. If primary fails → fallback to Traffic Cop
3. If all cloud models fail → graceful degrade to `local_only_mode`
4. If local also fails → `DEGRADED_AUTH` state, passive observation only

All inference calls are decoupled from the asyncio event loop via a `ThreadPoolExecutor(max_workers=4)` to prevent I/O blocking.

### The Host Executor (Privileged Intent Gateway)

A root-level asyncio daemon that processes typed intents via UNIX domain socket:

| Intent | Action | Pre-flight |
|--------|--------|------------|
| `BLOCK_IP` | `ufw deny from <ip>` | BTRFS snapshot |
| `SYSTEM_UPDATE` | `pacman -Syu --noconfirm` | BTRFS snapshot |
| `RESTART_DAEMON` | `systemctl restart yantra.service` | BTRFS snapshot |
| `PRUNE_SNAPSHOTS` | `snapper cleanup timeline` | — |
| `SYNC_CLOCK` | `timedatectl set-ntp true` | — |
| `UPDATE_SECRETS` | Write to `/etc/yantra/host_secrets.env` | BTRFS snapshot |
| `ENABLE_DAEMON` | `systemctl enable yantra.service` | — |
| `DISABLE_DAEMON` | `systemctl disable yantra.service` | — |
| `STOP_DAEMON` | `systemctl stop yantra.service` | — |
| `RELOAD_DAEMON_CONFIGS` | `systemctl daemon-reload` | — |

**Security invariants:**
- Raw shell strings are **REJECTED** — only typed intent schemas accepted
- Every destructive intent is gated by a **BTRFS pre-flight snapshot**
- All subprocess calls use explicit argument lists — **never `shell=True`**
- Socket permissions: `root:yantra 0660`
- Input sanitization: target fields validated against `[a-zA-Z0-9_.-]`

---

## 6. COMPLETE FEATURE LIST

### Core Intelligence
| Feature | Detail |
|---------|--------|
| **Kriya Loop Engine** | Perpetual 3-phase cognitive cycle (SENSE → REASON → ACT) with 10-second iteration interval |
| **Hybrid Inference Router** | Dual-tiered LiteLLM-powered model routing with automatic failover (Azure → Moonshot → Local) |
| **Cognitive Tiering** | Watchdog tier (fast, cheap) for SENSE; Builder tier (powerful) for REASON/ACT |
| **Circuit Breaker** | 5 consecutive failures → flush cognitive context to prevent hallucination spirals |
| **Injection Retry Queue** | Failed operator tasks retry up to 3x with push notifications on each attempt |
| **Conversation History Management** | Rolling window of system prompt + last 4 messages prevents context bloat |
| **Deterministic Fallback Heuristics** | If LLM is unreachable: disk < 5GB → cleanup, VRAM > 90% → offload to cloud |
| **Self-Annealing Behavior** | Stores failure embeddings in ChromaDB; avoids repeating strategies with cosine similarity > 0.85 |

### Security
| Feature | Detail |
|---------|--------|
| **Docker Sandbox** | `network_mode=none`, `cap_drop=ALL`, `read_only=True`, `auto_remove=True`, `user=nobody`, `mem_limit=128m` |
| **Image Allowlist** | Only `alpine:3.19`, `alpine:3.20`, `alpine:latest`, `yantra-agent:latest` permitted |
| **Script Sanitization** | Max 64 KiB, NUL bytes stripped, environment vars limited to printable ASCII |
| **Execution Timeout** | 30-second hard kill on all sandbox operations |
| **Host Executor** | Root-level daemon with typed intents only — no raw shell execution |
| **BTRFS Pre-flight Snapshots** | Every destructive operation gated by atomic filesystem snapshot |
| **IPC Localhost Binding** | All privileged endpoints enforce `127.0.0.1` origin regardless of server bind address |
| **Pydantic extra=forbid** | Payload data minimization — all unrecognized JSON keys are rejected |
| **Unprivileged Daemon** | Main daemon runs as `yantra_daemon` (UID 999) with `ProtectSystem=strict`, `NoNewPrivileges=yes` |
| **Immutable Audit Log** | Append-only JSONL with SHA-256 fingerprint of every executed script |
| **Active Defense Protocol** | Automatic SSH brute-force detection and IP blocking via UFW |
| **Secret Management** | `/etc/yantra/secrets.env` (mode 0400), never interpolated into LLM context |

### Telemetry & Monitoring
| Feature | Detail |
|---------|--------|
| **Hardware Telemetry** | Real-time CPU, RAM, GPU (NVIDIA via pynvml, AMD via sysfs, Intel via lspci), disk, temperature |
| **SSH Auth Log Tailing** | Differential ingestion — reads only new lines, detects brute-force patterns |
| **Cloud Fleet Dashboard** | Live telemetry streaming to yantraos.com via aiohttp |
| **systemd Watchdog** | Independent heartbeat loop (15s interval) keeps systemd informed the daemon is alive |
| **State API** | `GET /state` on `127.0.0.1:50000` — full daemon state as JSON including BTRFS snapshot status |
| **Debug Endpoint** | `GET /debug` — secrets file integrity, env vars, router state, systemd drop-in, journal tail |

### Remote Control (Telegram C2 Gateway)
| Command | Action |
|---------|--------|
| `/report` | Full node status: phase, iteration, CPU, VRAM, disk, routing, model, last thought |
| `/task <instruction>` | Inject arbitrary task into the Kriya Loop with push notification on completion |
| `/debug` | Pull live diagnostics: secrets status, env vars, router mode, journal tail |
| `/route <tier> <model>` | Mutate the cognitive routing table in real-time |
| `/system <action>` | Dispatch sovereign system intents (RESTART_DAEMON, SYSTEM_UPDATE, etc.) |
| `/api <provider> <key>` | Emergency API key rotation via C2 channel |

### Memory & Learning
| Feature | Detail |
|---------|--------|
| **ChromaDB Vector Memory** | Persistent skill registry with semantic RAG search (768-dim embeddings) |
| **Hybrid Embedding Engine** | Ollama (local, `nomic-embed-text`) → Azure OpenAI (`text-embedding-3-small`) fallback |
| **Skill Schema v1** | `yantraos/skill/v1` — standardized skill format with execution environment metadata |
| **Zero-Vector Graceful Degradation** | If all embedding backends are offline, returns zero vectors to prevent crashes |

### Compliance & Data Sovereignty
| Feature | Detail |
|---------|--------|
| **DPDPA Section 8 Compliance** | Pydantic `extra="forbid"` data minimization on all IPC payloads |
| **DPDPA Section 12 — Right to Erasure** | Instant telemetry purge via `CONSENT_REVOKED` signal: SQLite + ChromaDB wipe |
| **Automated Data Mortality** | 24-hour TTL sweep on all telemetry records — hard delete, no soft delete |
| **Cryptographic Consent Ledger** | Ed25519-signed, append-only SQLite ledger with TPM 2.0-style PCR chain |
| **Consent Chain Integrity** | `PCR_n = SHA-256(PCR_{n-1} || measurement)` — tamper-evident consent history |

### TUI (Terminal User Interface)
| Feature | Detail |
|---------|--------|
| **3-Pane Textual HUD** | Telemetry (left) / ThoughtStream (center) / Command (right) |
| **Live IPC Streaming** | Connects to `/run/yantra/ipc.sock` for real-time cognitive telemetry |
| **Color System** | Electric Blue `#00E5FF` chrome, `#00FF41` confirmations, `#FFB000` alerts, `#888888` sub-text |
| **Zero Display Manager** | Boots directly to TTY1 — no Wayland, no X11, no compositor |

### Deployment
| Feature | Detail |
|---------|--------|
| **ArchISO Build Pipeline** | `compile_iso.sh` with amnesia protocol — purges all secrets before ISO compilation |
| **Docker Compose Headless MVP** | One-command deployment for cloud/VPS via `docker-compose up` |
| **Azure VHD Forge** | GitHub Actions CI workflow for automated Azure VM deployment |
| **QEMU Hypervisor** | Validated boot with `qemu-system-x86_64` headless serial console |

---

## 7. SECURITY MODEL

YantraOS takes an extreme "**default-deny, defense-in-depth**" approach. The threat model explicitly accounts for LLM hallucinations, prompt injection, and AI-generated malicious code.

### The Execution Chain

```
LLM OUTPUT → JSON Schema Validation → Docker Container
    → Restricted Alpine Shell → SSH (whitelisted key)
        → Host Command Executor (typed intents only)
```

Nothing bypasses this chain. No exceptions. No overrides.

### Threat Surface Analysis

| Threat | Mitigation |
|--------|------------|
| LLM hallucination → `rm -rf /` | LLM output is **NEVER** executed on the host. All scripts run in Docker with `read_only=True`, `network_mode=none` |
| Daemon privilege escalation | Daemon runs as `yantra_daemon` (UID 999). systemd enforces `ProtectSystem=strict`, `NoNewPrivileges=yes`, `PrivateTmp=yes` |
| Container escape to host filesystem | Docker has **NO** network, **NO** host mount, **NO** capabilities, `user=nobody` |
| Unrestricted SSH command execution | SSH key allows ONLY whitelisted commands from a hardcoded dispatch table |
| Secrets exfiltration via LLM prompt injection | Secrets in `/etc/yantra/secrets.env` (mode 0400). Never interpolated into model context. |
| IPC bridge interception / Remote execution | All privileged IPC endpoints strictly bound to `127.0.0.1`. Pydantic `extra="forbid"` drops all unexpected payload keys |
| Payload smuggling via extra JSON fields | Every IPC model uses Pydantic with `class Config: extra = "forbid"` |
| Memory exhaustion from rogue containers | `mem_limit=128MB`, `cpu_quota` enforced, 30-second timeout with auto-kill |
| Hallucination spiral (repeated failures) | Circuit Breaker: 5 consecutive failures → flush conversation history and start fresh |

---

## 8. THE TELEGRAM C2 GATEWAY

YantraOS operates headless and fully isolated, but you are always in control. The **Telegram C2 Gateway** provides an out-of-band asynchronous control plane directly from your smartphone.

### Architecture

```
Your Phone (Telegram App)
       │
       │ Telegram Bot API (TLS)
       ▼
telegram_gateway.py (aiogram)
       │
       │ HTTP (127.0.0.1:50000)
       ▼
Kriya Loop Engine (FastAPI IPC)
       │
       │ UNIX Domain Socket
       ▼
Host Executor (root)
```

### Key Design Decisions

1. **Operator Identity Verification** — A middleware silently drops any message not from the verified `TELEGRAM_OPERATOR_CHAT_ID`. No error response, no acknowledgment — unauthorized users see nothing.

2. **Push Notification Poller** — Background asyncio task polls `/notifications` every 3 seconds. Failed sends are retried up to 3x with exponential backoff. Notifications are consumed from the engine on fetch (exactly-once semantics).

3. **Safe Send Helper** — All messages sent as raw plain text (never MarkdownV2) to prevent silent aiogram parsing failures. Automatic chunking for messages exceeding Telegram's 4096-char limit.

4. **C2 Partition Resilience** — If the bot connection drops, it auto-reconnects after 60-second backoff. The daemon continues operating independently.

---

## 9. THE WEB HUD — FLEET DASHBOARD

The cloud dashboard at [yantraos.com](https://yantraos.com) provides real-time visualization of the fleet's health:

- **Live Telemetry Strip** — PINECONE state, MODEL routing, BUILD status
- **Engine Room** — 3-column architecture grid (CORE-01: Hybrid Inference, CORE-02: Vector Memory, CORE-03: Atomic Stability)
- **Interactive Terminal HUD** — Boot sequence simulation with live command input
- **Skill Store** — Browse and search autonomous behaviors via Pinecone semantic search
- **Node Telemetry** — CPU, RAM, GPU, VRAM, disk, and loop cycle count per registered node

**Stack:** Next.js 14, Tailwind CSS, Framer Motion, Vercel AI SDK, Supabase, Pinecone  
**Design:** Neobrutalist geometric law — `border-radius: 0px` everywhere, Electric Blue `#00E5FF` accent

---

## 10. DPDPA COMPLIANCE & DATA SOVEREIGNTY

YantraOS implements India's **Digital Personal Data Protection Act (DPDPA) 2023** at the operating system level:

### Cryptographic Consent Ledger

A simulated TPM 2.0 PCR (Platform Configuration Register) chain:

```
PCR_0 = 0x0000...0000 (initial state)
PCR_1 = SHA-256(PCR_0 || "CONSENT_GRANTED:1720000000.0")
PCR_2 = SHA-256(PCR_1 || "CONSENT_REVOKED:1720001000.0")
```

Each consent state change is:
1. Hashed with the previous PCR value (tamper-evident chain)
2. Signed with an Ed25519 private key
3. Recorded in an append-only SQLite ledger

### Right to Erasure (Section 12)

When `CONSENT_REVOKED` is received:
1. **SQLite telemetry store** — instant `DELETE FROM telemetry_store`
2. **ChromaDB vector embeddings** — `skill_index` and `execution_logs` collections purged
3. **Confirmation logged** with SHA-256 proof of deletion

### Automated Data Mortality

Every Kriya Loop iteration runs a TTL sweep:
- Records older than 24 hours are **hard-deleted** from SQLite
- Expired embeddings are purged from ChromaDB
- No soft deletes. No tombstones. Dead data is dead.

---

## 11. THE TECHNOLOGY STACK

```
LAYER               TECHNOLOGY              PURPOSE
────────────────────────────────────────────────────────────────
Boot                Arch Linux (linux-lts)  Stable, minimal kernel
Init                systemd                 Daemon lifecycle + watchdog
OS Interface        Python 3.12 / asyncio   Daemon orchestration
Inference Router    LiteLLM                 Model-agnostic API layer
Cloud Models        Azure OpenAI (gpt-5.4)  Primary cloud inference
                    Moonshot (kimi-k2.7)    Heavy-lifting reasoning
Local Inference     Ollama                  Private on-device LLMs
                    DeepSeek-V4-Flash       Local fallback model
Vector Memory       ChromaDB                Skill/context storage (768-dim)
Embedding (Local)   Ollama (nomic-embed)    Zero-cost embeddings
Embedding (Cloud)   Azure (text-embed-3)    Cloud embedding fallback
Execution Sandbox   Docker + Alpine         Safe command execution
Host SSH Gateway    OpenSSH (allowlist)     Whitelisted host control
TUI Framework       Textual + Rich          Terminal HUD renderer
IPC Transport       UNIX Domain Socket      Daemon <-> UI bridge
State API           FastAPI + Uvicorn       HTTP state server (127.0.0.1:50000)
C2 Gateway          aiogram + aiohttp       Telegram bot interface
Telemetry Cloud     Next.js + Supabase      Fleet monitoring dashboard
Deployment Host     Vercel                  www.yantraos.com
Secret Management   pydantic-settings       /etc/yantra/secrets.env
Filesystem          Btrfs (+ Snapper)       Atomic snapshots
Skill Store         Pinecone (1536-dim)     Semantic skill retrieval (cloud)
Consent Ledger      SQLite + Ed25519        DPDPA compliance chain
Audit Trail         JSONL + SHA-256         Immutable execution log
OTA Manager         systemd + pacman hook   Autonomous self-update
CI/CD               GitHub Actions          Azure VHD forge + deploy
Documentation       GitBook                 yantraos.gitbook.io
```

---

## 12. GETTING STARTED

### Option A: Docker Compose (Cloud/VPS — Quickest)

```bash
git clone https://github.com/AIYantra/YantraOS.git
cd YantraOS

# Configure secrets
cp host_secrets.env.template .env
$EDITOR .env

# Launch
docker-compose up -d
```

### Option B: Bare-Metal (Full Experience)

```bash
git clone https://github.com/AIYantra/YantraOS.git
cd YantraOS

# Build the ArchISO (requires: archiso, Docker, root)
cd archlive
sudo bash compile_iso.sh

# Flash to USB
sudo dd if=out/yantraos-*.iso of=/dev/sdX bs=4M status=progress

# Boot → yantra_ignition.sh → Kriya Loop begins
```

### Option C: QEMU (Virtualized Testing)

```bash
qemu-system-x86_64 \
  -m 4G \
  -enable-kvm \
  -cpu host \
  -drive file=yantraos-*.iso,format=raw,if=virtio \
  -nographic \
  -serial mon:stdio
```

### Option D: Run Locally (Dev Mode)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m core.daemon     # Start the Kriya Loop
python3 -m core.tui_shell  # Launch the TUI (separate terminal)
```

---

## 13. COMPLETE DEVELOPMENT TIMELINE

### February 14 – March 27, 2026 — Genesis

| Date | Milestone |
|------|-----------|
| Feb 14 | Project inception. Core daemon scaffold (`daemon.py`, `engine.py`) |
| Feb–Mar | IPC bridge via UNIX domain socket, FastAPI ASGI server |
| Feb–Mar | Textual TUI — 3-pane HUD (Telemetry / ThoughtStream / Command) |
| Feb–Mar | ChromaDB async vector memory with graceful degradation |
| Feb–Mar | LiteLLM hybrid inference router (Local + Cloud fallback) |
| Feb–Mar | Docker sandbox: `network_mode=none`, `cap_drop=ALL`, `read_only=True` |
| Feb–Mar | BTRFS auto-snapshots via pacman hook |
| Feb–Mar | systemd watchdog integration (`WatchdogSec=15`) |
| Feb–Mar | Pinecone skill store index (1536-dim cosine) |
| Mar 27 | **v1.0-alpha ISO released** — First bootable artifact (2.4 GB, split into 3 parts) |

### March 27 – June 10, 2026 — Hardening & Web HUD

| Date | Milestone |
|------|-----------|
| Mar–May | Web HUD at yantraos.com — Next.js 14, Tailwind, Framer Motion |
| Mar–May | Supabase auth, operator handles, genesis badges, blog system |
| Mar–May | Aggressive SEO overhaul, LLMO directives for AI crawlers |
| May–Jun | Fleet telemetry dashboard with real-time node monitoring |
| Jun 1 | **v0.2 released** — Localhost guard on `/inject`, SSH gateway hardening, vector dim fix |
| Jun 5 | **v0.2.1** — Fixed `_assert_localhost` TypeError at `/inject` endpoint |
| Jun 10 | **v0.2.2** — Added `/debug` endpoint and Telegram diagnostic command |

### June 11 – July 1, 2026 — Headless MVP & Azure Integration

| Date | Milestone |
|------|-----------|
| Jun 11 | Latest changes sync |
| Jun 22 | Headless MVP refactor — cloud-only router, audit logging, Docker Compose deployment |
| Jun 22 | Azure OpenAI integration (gpt-4o-mini → gpt-4.1-mini → gpt-5.4-mini) |
| Jun 23 | Circuit Breaker — LLM self-healing with conversation history matrix |
| Jun 23 | Active Defense Protocol — UFW intent corridor, autonomous threat response |
| Jun 23 | Host Executor UDS client — typed intents via UNIX socket |
| Jun 24 | Cognitive Tiering — Watchdog/Builder tiers with stateful SENSE log tailing |
| Jul 1 | Azure OpenAI gpt-5.4-mini integration, expanded context window buffer |
| Jul 1 | Genesis Skill Provisioning with ChromaDB |
| Jul 1 | Excised PyTorch/sentence-transformers — embeddings now route through Ollama+Azure |
| Jul 1 | ChromaDB 1.5.9 compatibility fixes (embedding function contract) |
| Jul 1 | `/state` API + Threat Intelligence Dashboard compositor |
| Jul 1 | Non-blocking secure fleet telemetry implementation |
| Jul 1 | Differential log ingestion to prevent context bloat |
| Jul 1 | ArchISO profile scaffold with YantraOS customizations |

### July 5–6, 2026 — Azure Cloud Forge & Telegram

| Date | Milestone |
|------|-----------|
| Jul 5 | Azure VHD forge CI workflow — automated cloud VM deployment |
| Jul 5 | pacman dependency fixes for Ubuntu runner, VM SKU capacity management across regions |
| Jul 6 | **Telegram C2 Gateway** — `/report`, `/task`, `/route`, `/system`, `/api` commands |
| Jul 6 | DPDPA ComplianceExecutor — consent ledger, data mortality, right to erasure |
| Jul 6 | Sandbox failure bubbling and timeout enforcement |
| Jul 6 | MarkdownV2 escaping fixes → switched to raw text for reliability |

### July 7–8, 2026 — Security Hardening Sprint

| Date | Milestone |
|------|-----------|
| Jul 7 | Push notifications for task completions — async poller with retry queue |
| Jul 7 | LLM prompt rewrite — force-execute priority injected tasks |
| Jul 7 | Cognitive override isolation — conversation history wipe on injection |
| Jul 7 | v0.2 release blockers: localhost binding, auth guards, vector dim fix, TG retry queue |
| Jul 8 | Injection retry tracking — 3x retry with operator notifications |
| Jul 8 | **v0.2.1** — Fixed TypeError in `_assert_localhost` |
| Jul 8 | **v0.2.2** — `/debug` endpoint and TG command |
| Jul 8 | **v0.2.3** — Azure OpenAI secrets injection into VHD builds |
| Jul 8 | LLM hallucination fix — notification spam eliminated |

### July 8–9, 2026 — Launch Preparation

| Date | Milestone |
|------|-----------|
| Jul 8 | Comprehensive v0.2.4 documentation update |
| Jul 8 | GitBook sync trigger |
| Jul 8 | Professional repository health files (issue templates, PR template, CI workflows) |
| Jul 9 | **Microsoft for Startups** partnership badge integrated |
| Jul 9 | CHANGELOG.md created with full release history |
| Jul 9 | **v0.2.4 released on GitHub** |

---

## 14. VERSION HISTORY

| Version | Date | Codename | Highlights |
|---------|------|----------|------------|
| **v0.2.4** | Jul 9, 2026 | Security Hardening | Telegram C2 Gateway, IPC hardening, cognitive override interrupts, Microsoft for Startups, CHANGELOG |
| **v0.2.3** | Jul 8, 2026 | Cloud Forge | Azure OpenAI secrets injection into VHD builds |
| **v0.2.2** | Jul 8, 2026 | Debug | `/debug` endpoint and Telegram diagnostic command |
| **v0.2.1** | Jul 8, 2026 | Hotfix | Fixed `_assert_localhost` TypeError at `/inject` |
| **v0.2** | Jul 8, 2026 | Foundation | Localhost guard, SSH gateway, vector memory fixes, Telegram retry queue |
| **v1.0-alpha** | Mar 27, 2026 | The Karma Yogi | First bootable ISO (2.4 GB), complete Kriya Loop, Docker sandbox, TUI |

---

## 15. WHAT'S NEXT — ROADMAP

| Priority | Feature | Status |
|----------|---------|--------|
| High | **Multi-node fleet management** — Alpha + Edge topology | In design |
| High | **Full LLM → Docker → SSH → Host end-to-end test** | In review |
| Medium | **NVIDIA proprietary driver injection on live ISO** | Pending |
| Medium | **Skill Store marketplace** — public skill publishing and acquisition | Stubbed |
| Future | **Rust rewrite of performance-critical paths** | Planned for v2 |
| Future | **WebGL 3D fleet visualization** | Exploring |
| Future | **Mobile companion app** | Planned |

---

## 16. PRESS KIT & LAUNCH COPY

### ProductHunt Maker Comment (Draft)

> **Hey ProductHunt!** 👋
>
> I'm launching **YantraOS** — the world's first Autonomous Agent Operating System.
>
> The idea is simple but radical: **what if your computer could think for itself?**
>
> YantraOS is a real operating system (Arch Linux) with a Python daemon that runs a perpetual cognitive loop called the **Kriya Loop**. Every 10 seconds, it:
> 1. **SENSES** — monitors CPU, RAM, GPU, disk, SSH logs
> 2. **REASONS** — sends telemetry to an LLM for analysis
> 3. **ACTS** — executes commands in a locked-down Docker sandbox
> 4. **LEARNS** — embeds outcomes in vector memory
>
> The security model is paranoid by design. Every AI-generated script runs in a container with no network, no filesystem access, no capabilities. The daemon can't crash the UI. The UI can't deadlock the engine.
>
> You can control it from your phone via a Telegram bot, and it streams live telemetry to a cloud dashboard at yantraos.com.
>
> It's MIT licensed, backed by Microsoft for Startups, and completely open source.
>
> We'd love your feedback. AMA! 🚀

### BetaList Description (Draft)

> **YantraOS** is an autonomous agent operating system built on Arch Linux. A background daemon continuously monitors your machine, reasons about its state using LLMs, and takes corrective actions in a security-hardened Docker sandbox — all without human intervention.
>
> Features include a hybrid cloud/local inference engine, a Telegram control gateway, DPDPA-compliant data sovereignty, and a real-time fleet dashboard. Open source (MIT).

### Key Stats for Press

| Metric | Value |
|--------|-------|
| Lines of core Python | ~3,500+ across 17 modules |
| Git commits | 165+ since inception |
| GitHub releases | 6 (v1.0-alpha through v0.2.4) |
| Cognitive cycle interval | 10 seconds |
| Docker sandbox constraints | `network=none`, `read_only`, `cap_drop=ALL`, `user=nobody`, `mem_limit=128MB` |
| IPC transport | UNIX Domain Socket (zero network overhead) |
| License | MIT |
| Partnership | Microsoft for Startups Founders Hub |
| Funding model | Open Collective (100% transparent) |

---

> *"The computer was always capable of thinking. We just never asked it to."*  
> — YantraOS

**[yantraos.com](https://yantraos.com)** · **[GitHub](https://github.com/AIYantra/YantraOS)** · **[Documentation](https://yantraos.gitbook.io)** · **[Discord](https://discord.gg/tkg6XQBPpK)** · **[Open Collective](https://opencollective.com/yantraos)**
