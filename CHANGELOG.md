# Changelog

All notable changes to YantraOS are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.4] — 2026-07-09

### Added
- **Microsoft for Startups Partnership** — Official partnership badge and documentation integrated into repository.
- **Telegram C2 Gateway** — Asynchronous push notifications for completed/failed priority intents, `/debug` diagnostic command, and mission override injection from mobile.
- **Cognitive Override Interrupts** — Priority injection system with strict prompt isolation and conversation history wiping to prevent LLM hallucinations during operator-issued commands.
- **IPC Security Docs** — New `docs/security/ipc-hardening.md` documentation for the hardened IPC protocol.
- **Professional Repository Health Files** — GitHub issue templates (bug report, feature request), PR template, auto-assign workflow, and PR checks CI.
- **GitBook Documentation Sync** — Initial content push to trigger GitBook integration for `yantraos.gitbook.io`.

### Fixed
- **LLM Instruction Hallucination** — Resolved engine hallucinations during priority task injections by isolating prompt context.
- **Telegram Notification Spam** — Fixed duplicate and excessive notifications when processing injected intents.
- **Comprehensive Diagnostics** — Added `/debug` endpoint exposing secrets file status, environment variables, router state, and systemd drop-in configuration.

### Changed
- **IPC Hardening** — Enforced `127.0.0.1` binding for all privileged endpoints (`/inject`, `/api/v1/config/route`); strict Pydantic payload data minimization with `extra="forbid"`.
- **Cloud Forge Integrity** — Automated injection of Azure OpenAI API keys into VHD builds.
- **Retry Queue** — Engine retry queue (up to 3×) for failed intents with operator notifications on each attempt.

### Security
- Strict localhost binding on all privileged IPC endpoints prevents remote code execution via payload smuggling.
- Pydantic `extra="forbid"` drops all unrecognized payload keys to prevent injection via unexpected fields.

---

## [0.2.3] — 2026-06-15

### Fixed
- **Azure OpenAI Secrets** — Injected missing Azure OpenAI API keys into `host_secrets.env` for VHD deployments.
- **Cloud Forge Deploy** — Fixed VHD rebuild pipeline to correctly propagate secrets through the build chain.

---

## [0.2.2] — 2026-06-10

### Added
- **`/debug` Endpoint** — New IPC and Telegram command for real-time troubleshooting: dumps secrets file integrity, environment variables, hybrid router state, and systemd drop-in configuration.

### Fixed
- **Comprehensive Diagnostics** — Full debug introspection pipeline for production issue triage.

---

## [0.2.1] — 2026-06-05

### Fixed
- **IPC Server TypeError** — Fixed `_assert_localhost` call signature at the `/inject` endpoint that was crashing on valid localhost connections.

---

## [0.2] — 2026-06-01

### Added
- **Kriya Loop Daemon** — Complete SENSE → REMEMBER → REASON → ACT → LEARN cognitive cycle.
- **Hybrid Inference Engine** — LiteLLM-powered model-agnostic routing (Ollama local → Azure/Gemini cloud fallback).
- **IPC Bridge** — FastAPI ASGI server over UNIX Domain Socket (`/run/yantra/ipc.sock`) with 8 registered actions.
- **Textual TUI** — 3-pane terminal HUD (Telemetry / ThoughtStream / Command) with live SSE streaming.
- **Skill Store** — Pinecone `yantra-skills` index (1536-dim cosine) with semantic RAG search.
- **Autonomous OTA Evolution** — systemd + pacman hook pipeline with BTRFS pre-snapshot guarantees.
- **Docker Sandbox** — Locked-down Alpine container for all LLM-generated command execution.
- **Cloud Telemetry** — Heartbeat broadcast to `yantraos.com` fleet dashboard via Supabase.
- **ArchISO Build Pipeline** — `compile_iso.sh` with amnesia protocol and 6-invariant hardening.

### Security
- Daemon runs as `yantra_daemon` (UID 999) with `ProtectSystem=strict`, `NoNewPrivileges=yes`.
- Docker sandbox: `network_mode="none"`, `user="nobody"`, `cap_drop=["ALL"]`.
- Secrets stored at `/etc/yantra/secrets.env` (mode 0400), never interpolated into LLM context.
- SSH gateway restricted to whitelisted commands only.
- Localhost guard on `/inject` endpoint to prevent remote execution.

---

## [1.0-alpha] — 2026-03-27

### Added
- **v1.0 Alpha ISO Release** — First bootable ArchISO artifact (`YantraOS-v1.0-alpha-x86_64.iso`, 2.4 GB).
- **Cognitive Ignition Wizard** — Interactive `yantra_ignition.sh` for first-boot API key provisioning.
- **NVIDIA Module Injection** — `mkinitcpio` configuration for proprietary NVIDIA driver support.
- **BTRFS Auto-Snapshots** — pacman hook for pre-transaction atomic snapshots.
- **Fleet Telemetry** — Non-blocking secure telemetry broadcast to cloud dashboard.
- **Circuit Breaker** — LLM self-healing with conversation history matrix and retry logic.
- **Active Defense Protocol** — UFW intent corridor with autonomous threat response.

---

[0.2.4]: https://github.com/AIYantra/YantraOS/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/AIYantra/YantraOS/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/AIYantra/YantraOS/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/AIYantra/YantraOS/compare/v0.2...v0.2.1
[0.2]: https://github.com/AIYantra/YantraOS/compare/v1.0-alpha...v0.2
[1.0-alpha]: https://github.com/AIYantra/YantraOS/releases/tag/v1.0-alpha
