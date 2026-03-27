```
██████╗ ███████╗██╗     ███████╗ █████╗ ███████╗███████╗
██╔══██╗██╔════╝██║     ██╔════╝██╔══██╗██╔════╝██╔════╝
██████╔╝█████╗  ██║     █████╗  ███████║███████╗█████╗
██╔══██╗██╔══╝  ██║     ██╔══╝  ██╔══██║╚════██║██╔══╝
██║  ██║███████╗███████╗███████╗██║  ██║███████║███████╗
╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝

         TRANSMISSION // RELEASE MANIFEST
         CLASSIFICATION: GOLDEN MASTER // PRE-ALPHA
         ARTIFACT: YantraOS-v1.0-alpha-x86_64.iso
         COMPILED: 2026-03-27T00:00:00Z
         NODE: alpha-01 // The Karma Yogi Awakens
```

---

# YANTRAOS v1.0 ALPHA — GOLDEN MASTER RELEASE MANIFEST

> *"यन्त्र"* — Sanskrit: A geometric instrument of divine computation.
> A structured pathway through which consciousness operates on matter.
>
> **This is not software. This is an act of will encoded in silicon.**

---

## ⛔ OPERATOR SAFETY DIRECTIVE — READ BEFORE PROCEEDING

```
╔══════════════════════════════════════════════════════════════════════╗
║                  !! PRE-ALPHA — CRITICAL WARNING !!                  ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  THIS IS A PRE-ALPHA RELEASE. IT IS NOT A DAILY DRIVER.             ║
║                                                                      ║
║  DO NOT INSTALL THIS ON BARE METAL AS YOUR PRIMARY OPERATING        ║
║  SYSTEM. DATA LOSS, KERNEL PANICS, AND DAEMON INSTABILITY           ║
║  ARE ANTICIPATED UNDER UNTESTED HARDWARE CONFIGURATIONS.            ║
║                                                                      ║
║  AUTHORIZED DEPLOYMENT ENVIRONMENT: QEMU / KVM ONLY.               ║
║                                                                      ║
║  You have been warned. The Karma Yogi does not offer refunds.       ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

**This artifact is intended for:** security researchers, AI systems engineers, OS hackers, and autonomy pioneers who understand the risks of running an AI-governed execution environment and accept full operational responsibility.

---

## `[01]` — WHAT THIS IS

YantraOS v1.0 Alpha is the **world's first Level 3 Autonomous Agent Operating System** — a bare-metal Arch Linux foundation running a continuous Python asyncio **Kriya Loop** that reasons via LiteLLM and executes in a locked-down Docker sandbox.

It does not wait for your input. It does not sleep. It monitors. It decides. It acts.

This Golden Master ISO represents the culmination of a complete four-phase development cycle:

| Phase | Codename | Status |
|:------|:---------|:------:|
| Phase 1 | Core Daemon · The Kriya Loop | `[COMPLETE]` |
| Phase 2 | IPC Bridge · The Yantra Shell TUI | `[COMPLETE]` |
| Phase 3 | Skill Store · Pinecone Vector Memory | `[COMPLETE]` |
| Phase 4 | Autonomous OTA Evolution Engine | `[COMPLETE]` |

---

## `[02]` — THE ARCHITECTURE STACK

```
LAYER               TECHNOLOGY                  PURPOSE
────────────────────────────────────────────────────────────────────────
Boot                Arch Linux (linux-lts)       Minimal, rolling kernel
Init                systemd                      Daemon lifecycle + IPC
OS Orchestration    Python 3.12 / asyncio        The Kriya Loop engine
Inference Router    LiteLLM                      Model-agnostic API layer
Local Inference     Ollama (Llama 3 / Phi-3)     100% air-gapped on-device
Vector Memory       ChromaDB                     Async RAG, skill context
Execution Sandbox   Docker Alpine                Isolated blast radius
IPC Transport       UNIX Domain Socket           /run/yantra/ipc.sock
TUI Framework       Textual + Rich               3-pane terminal HUD
Skill Store         Pinecone (1536-dim cosine)   Semantic skill retrieval
Cloud Telemetry     Next.js + Supabase           Fleet monitoring HUD
Secret Management   pydantic-settings            /etc/yantra/secrets.env
Filesystem          Btrfs (+ Snapper hooks)      Atomic OTA snapshots
OTA Manager         systemd + pacman hooks        Autonomous self-update
```

**The Cognitive Cycle — The Kriya Loop:**

```
    ┌──────────────────────────────────────────────────────┐
    │                                                      │
    ▼                                                      │
[ SENSE ]  ── CPU · RAM · GPU · Disk · Logs · Temps       │
    │                                                      │
    ▼                                                      │
[ REMEMBER ] ── ChromaDB Vector Search · Past Context     │
    │                                                      │
    ▼                                                      │
[ REASON ] ── LiteLLM Inference · Local → Cloud Fallback  │
    │                                                      │
    ▼                                                      │
[ ACT ] ── Docker Alpine Sandbox · Whitelisted SSH         │
    │                                                      │
    ▼                                                      │
[ LEARN ] ── Embed Outcome · Heartbeat to Cloud           │
    │                                                      │
    └──────────────────────────────────────────────────────┘
                          ∞  forever
```

---

## `[03]` — THE GOLDEN MASTER ARTIFACT

The compiled ISO exceeded GitHub's 2 GB file size limit at **2.4 GB**. The Golden Master was therefore subjected to a **Split Protocol**, dividing the artifact into three sequential binary segments for distribution integrity.

```
ARTIFACT REGISTRY
═══════════════════════════════════════════════════════════════
  filename:    YantraOS-v1.0-alpha-x86_64.iso
  version:     1.0.0-alpha
  arch:        x86_64
  size:        2.4 GB (reassembled)
  format:      Raw bootable ISO (hybrid MBR/GPT)
  split into:  partaa  ·  partab  ·  partac
═══════════════════════════════════════════════════════════════

INTEGRITY VERIFICATION
═══════════════════════════════════════════════════════════════
  algorithm:   SHA-256
  hash:        aa655bbdfbeb265af453375be490c8b7acdb50f7c8f85051a96923fd865a0847
═══════════════════════════════════════════════════════════════
```

> **This hash is the ground truth.** If your reassembled ISO does not match
> this checksum exactly, the artifact is corrupt. Do not boot it.

---

## `[04]` — REASSEMBLY PROTOCOL

The split segments must be reassembled in sequential order before use. Execute the following protocol precisely:

**Step 1 — Verify part file presence:**

```bash
ls -lh YantraOS-v1.0-alpha-x86_64.iso.part*
# Expected: partaa  partab  partac
```

**Step 2 — Concatenate segments into the Golden Master ISO:**

```bash
cat YantraOS-v1.0-alpha-x86_64.iso.part* > YantraOS-v1.0-alpha-x86_64.iso
```

**Step 3 — Verify cryptographic integrity:**

```bash
sha256sum -c sha256sum.txt
```

Expected output:

```
YantraOS-v1.0-alpha-x86_64.iso: OK
```

> ⚠️ If verification fails with `FAILED`, abort. Do not proceed. The artifact
> was corrupted during download. Re-download all three parts and repeat.

---

## `[05]` — BOOT WITH QEMU

This build is validated exclusively within a **QEMU/KVM virtualized environment**. The following command injects the ISO as a virtio block device and runs headless over serial — the correct interface for a machine with no display manager:

```bash
qemu-system-x86_64 \
  -m 4G \
  -enable-kvm \
  -cpu host \
  -drive file=YantraOS-v1.0-alpha-x86_64.iso,format=raw,if=virtio \
  -nographic \
  -serial mon:stdio
```

**Parameter Annotations:**

| Flag | Effect |
|:-----|:-------|
| `-m 4G` | Allocate 4 GB RAM minimum. 8 GB recommended for local inference. |
| `-enable-kvm` | Hardware-accelerated virtualization. Requires `kvm` kernel modules loaded on host. |
| `-cpu host` | Exposes host CPU feature flags. Required for correct `linux-lts` boot. |
| `if=virtio` | VirtIO block transport. Faster than IDE/SCSI for ISO boot. |
| `-nographic` | Disables QEMU window. All I/O via serial terminal. |
| `-serial mon:stdio` | Muxes the QEMU monitor and serial console. Press `Ctrl+A C` to access monitor. |

---

## `[06]` — IGNITION SEQUENCE

Upon successful boot, the system will auto-login as `yantra_user` and launch the Textual TUI HUD. The **Kriya Loop daemon** (`yantra.service`) will be running in the background via systemd.

However, the **Karma Yogi is dormant** until its inference credentials are injected. Execute the ignition script to awaken the agent:

```bash
./yantra_ignition.sh
```

This script performs the following operations in sequence:

```
IGNITION SEQUENCE
═══════════════════════════════════════════════════════════════════
  [1] Prompt for API keys:
        · LiteLLM backend selection (Local / Cloud / Hybrid)
        · Gemini API Key (for cloud inference fallback)
        · Pinecone API Key (for Skill Store vector memory)
        · Supabase credentials (for cloud fleet telemetry)

  [2] Write secrets to /etc/yantra/secrets.env (mode: 0400)
        · Owner: yantra_daemon (UID 999)
        · Never interpolated into model context

  [3] Reload yantra.service to inject the new configuration

  [4] Verify IPC socket handshake on /run/yantra/ipc.sock

  [5] Stream the first Kriya Loop cycle to the TUI ThoughtStream
═══════════════════════════════════════════════════════════════════
```

When you see the following in the ThoughtStream pane, the Karma Yogi is alive:

```
[SENSE]   :: telemetry acquired. cpu=XX% ram=X.XGB
[REMEMBER]:: vector context loaded from ChromaDB
[REASON]  :: LiteLLM inference complete. action selected.
[ACT]     :: dispatching to Docker sandbox...
[LEARN]   :: outcome embedded. loop_cycle=00001
```

The machine is now thinking on your behalf.

---

## `[07]` — SECURITY MODEL SUMMARY

```
THREAT SURFACE              MITIGATION
═══════════════════════════════════════════════════════════════════════
LLM hallucination → exec    All LLM output is NEVER executed on host.
                            Routes exclusively through Docker Alpine.

Daemon privilege esc.       Daemon runs as yantra_daemon (UID 999).
                            systemd: ProtectSystem=strict,
                                     NoNewPrivileges=yes,
                                     PrivateTmp=yes

Container escape            Docker: network_mode="none",
                                    user="nobody",
                                    cap_drop=["ALL"]

Secrets in LLM context      /etc/yantra/secrets.env (0400 yantra_daemon)
                            Never interpolated into inference prompts.

Host command execution      SSH allowlist only. No os.system(). No
                            subprocess on host outside Polkit rules.
```

---

## `[08]` — KNOWN ALPHA LIMITATIONS

```
STATUS      COMPONENT
════════════════════════════════════════════════════════════
[PARTIAL]   SSH whitelisted command gateway (implemented,
            not fully validated on all hardware variants)

[PENDING]   NVIDIA proprietary driver injection on live ISO
            (nouveau fallback active in this build)

[PENDING]   Full end-to-end test: LLM → Docker → SSH → Host
            (sandboxed exec validated; SSH gateway in review)

[PENDING]   Multi-node fleet management topology
            (Alpha-01 single-node; Edge mode stubbed)

[KNOWN BUG] GRUB timeout on certain UEFI implementations —
            append `nomodeset` to kernel params if boot stalls
```

---

## `[09]` — MANIFEST SIGNATURE

```
╔══════════════════════════════════════════════════════════════════════╗
║  RELEASE METADATA                                                    ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  Project:    YantraOS                                                ║
║  Codename:   The Karma Yogi                                          ║
║  Version:    v1.0.0-alpha (Golden Master)                            ║
║  Build Date: 2026-03-27                                              ║
║  Target:     x86_64 bare-metal / QEMU                               ║
║  License:    MIT                                                     ║
║  Publisher:  AIYantra (github.com/AIYantra)                          ║
║  Homepage:   https://yantraos.com                                    ║
║  Docs:       https://yantraos.gitbook.io                             ║
║                                                                      ║
║  ISO SHA-256:                                                        ║
║  aa655bbdfbeb265af453375be490c8b7acdb50f7c8f85051a96923fd865a0847   ║
║                                                                      ║
║  "The computer was always capable of thinking.                       ║
║   We just never asked it to."                                        ║
║                                      — YantraOS                     ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

<div align="center">

**[`yantraos.com`](https://yantraos.com)** · **[`Documentation`](https://yantraos.gitbook.io)** · **[`GitHub`](https://github.com/AIYantra/YantraOS)**

`/run/yantra/ipc.sock` · `∞` · `यन्त्र`

</div>
