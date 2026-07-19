# YantraOS Internal Project Memory

**Last updated:** 2026-07-14  
**Audience:** future engineering agents and maintainers  
**Current milestone:** M5 file management implemented, unverified; remaining M3 cleanup tracked  
**Baseline:** `v0.2.4-ops-agent-baseline` on `main`

## Purpose

This file is the concise internal source of truth for continuing YantraOS work. It records the current product direction, actual implementation, milestone state, safety boundaries, known discrepancies, and operating practices.

It is intentionally candid. Do not convert planned behavior into completed behavior, and do not repeat README claims without checking current code or verified test evidence.

## Authority Order

When sources disagree, use this order:

1. Explicit current direction from the founder/user.
2. `../YantraOS_Vision_Execution_Roadmap.md`.
3. `SCOPE_FREEZE.md`.
4. `VISION_CHECKLIST.md`.
5. Current code and verified test evidence.
6. `README.md` and older architecture documents.

The July 2026 execution roadmap supersedes older product plans. The README remains useful for vision and historical context, but several architecture and completion claims no longer match the working tree.

## Status Vocabulary

Use these labels in future work:

- **Complete:** project authority has accepted the milestone.
- **Verified:** directly demonstrated by a test or observed run.
- **Implemented, unverified:** code exists but its real integration or reliability gate has not been demonstrated.
- **Planned:** roadmap intent only.
- **Historical:** older behavior or documentation that is no longer authoritative.

## Product Vision

YantraOS aims to invert the conventional operating-system relationship:

```text
Traditional: Human -> Input -> OS -> Output
YantraOS: OS senses context -> reasons -> acts -> human observes and overrides
```

The target is an autonomous orchestration layer on Arch Linux with:

- A persistent Kriya Loop.
- Hybrid local/cloud reasoning.
- Natural-language control of real applications and system operations.
- Typed privileged intents rather than arbitrary root shell commands.
- Confirmation, audit, rollback, circuit breaking, and human override.
- Graceful degradation instead of daemon-wide failure.
- One primary command/chat interface.

The immediate strategy is reliability-first. Generated code is not acceptance; repeated bare-metal operation is the meaningful gate.

## Current Milestone State

### M0 - Baseline Freeze

Complete in repository terms:

- Baseline tag: `v0.2.4-ops-agent-baseline`.
- `SCOPE_FREEZE.md` exists.
- `VISION_CHECKLIST.md` exists.

Azure resource-group and budget-alert state cannot be verified from this workspace.

### M1 - Action Primitive

Implemented through `core/foundry_action_bridge.py` and related tests. The implementation uses local Playwright plus Azure OpenAI rather than the exact Foundry Agent Service and attached Browser Automation Tool architecture described in the roadmap.

### M2 - Computer Use

**Complete by explicit project authority as of 2026-07-13.** Treat M2 as closed for milestone planning and proceed toward M3 unless the founder explicitly reopens it.

Verified during bare-metal testing:

- KDE launcher opened through physical key events.
- Applications were searched and launched.
- Telegram opened successfully.
- Saved Messages was found through keyboard navigation.
- The exact message `hi` was typed, sent, and visually verified.
- The successful Telegram workflow completed in 16 steps.
- Chrome, Gmail, and Google Calendar navigation progressed through real clicks and typing.
- KDE/Wayland pointer calibration fixed absolute-click failures.
- Clipboard and unchanged-screen safeguards have focused unit coverage.

M2 implementation includes:

- Screenshot capture through Spectacle.
- Screenshot scaling to a maximum width of 1024 pixels.
- Screenshot-driven one-action-at-a-time model reasoning.
- `ydotool` click, type, and raw key-event execution.
- Correct splitting of multi-event key sequences into separate CLI arguments.
- KDE pointer reset plus relative movement compensation.
- `YDOTOOL_POINTER_SCALE`, currently calibrated to `2.0` on the test machine.
- Explicit `clipboard_copy` and `clipboard_paste` actions using Wayland clipboard tools.
- Perceptual screenshot-difference detection.
- Exit code `4` after two ineffective interactive actions.
- Confirmation and audit hooks.
- A current maximum of 200 model/action steps.

Documentation follow-up:

- `VISION_CHECKLIST.md` still has every item unchecked and must be synchronized with the accepted milestone state.
- The roadmap still describes a 30-step cap, while current code uses 200.
- No durable five-day test record is stored in the repository.
- These are documentation/evidence gaps, not an instruction to silently reopen M2.

### M3 - Kriya Integration

Partially implemented. Remaining outcomes must stay tracked while M5 begins:

- Route `EXTERNAL_ACTION` from the production engine ACT phase.
- Keep system-health scripts in the Docker sandbox.
- Remove the parallel-system split between `core/yantra_core.py` and the Kriya daemon.
- Route SENSE work to GPT-5.6 Luna, routine REASON work to GPT-5.6 Terra, and novel/ambiguous work to GPT-5.6 Sol.
- Use one shared five-consecutive-failure circuit-breaker budget.

Implemented, unverified as of 2026-07-13:

- `core/hybrid_router.py` maps SENSE/watchdog work to Luna, routine REASON/ACT work to Terra, and explicitly novel/ambiguous work to Sol.
- `core/engine.py` marks routine planning as REASON and operator-injected work as NOVEL.
- Deployment names are configurable through `AZURE_DEPLOYMENT_LUNA`, `AZURE_DEPLOYMENT_TERRA`, and `AZURE_DEPLOYMENT_SOL`.
- Focused deterministic routing tests pass, but no live Foundry inference has verified the three deployments.
- Sandbox, host-intent, socket, and EXTERNAL_ACTION failures share one five-consecutive-failure counter; focused mixed-action testing verifies that the fifth failure flushes cognitive context.

### M4 - Visual Intent Shell

**Complete by explicit project authority as of 2026-07-14.**

Verified during live KDE/Wayland testing:

- `ui/gui_shell.py` provides the selected PySide6 native Visual Intent Shell.
- The GUI sends strict `computer_use_task` EXTERNAL_ACTION payloads directly to `/run/yantra/executor.sock` on a background Qt thread.
- The GUI verifies the socket file and connected peer are root-owned, validates framed executor responses, rejects hidden Unicode controls, and renders all dynamic transcript content as plain sanitized text.
- Supervised external actions use a one-use, action-bound executor challenge displayed by the PySide6 GUI; host-confirmed computer-use tasks do not prompt again in the executor terminal, while per-step audit logging remains active.
- Focused socket-protocol and offscreen layout tests pass.
- The GUI rendered successfully in the real desktop session.
- GUI confirmation, executor validation, non-BTRFS pre-flight handling, Azure Foundry reasoning, and user-session computer use completed successfully end to end.
- The privileged executor retained typed-schema, confirmation, audit, and snapshot gates while launching Spectacle and ydotool as the logged-in desktop user rather than root.

### M5 - Verb Expansion

Implemented, unverified as of 2026-07-14:

- `file_management` is a strict `EXTERNAL_ACTION` type for bounded create, visual move, and visual read tasks; delete is disabled. Create uses exclusive mode-`0600` filesystem creation, then Sol verifies the listing in Dolphin.
- It reuses the existing unprivileged KDE/Wayland bridge: Spectacle for screenshots, GPT-5.6 Sol for spatial reasoning, and ydotool/Wayland clipboard tools for interaction.
- Paths are visible relative names confined to `~/Documents/YantraOS`; absolute/hidden/traversal paths, symlink escapes, foreign ownership, and overwrites fail closed. An owned permissive root is repaired to mode `0700`.
- All file actions use the shared first-20 confirmation and audit flow. Moves always require approval after run 20; audit logs hash-redact file content.
- File-task GUI policy rejects deletion/navigation shortcuts, right-click menus, clipboard replacement, and unverified completion before ydotool execution.
- File failures use the same engine five-consecutive-failure circuit breaker as browser, computer-use, and sandbox actions.
- `python -m core.yantra_core "<plain English file command>"` uses Sol to produce the typed payload and sends M5 actions through the Host Executor socket; users do not need to write JSON.
- Plain-English computer-use steps also route through the Host Executor, and multi-action plans stop when a prerequisite fails instead of continuing with missing files or state.
- Desktop automation supports model-proposed double-clicks and uses a bounded 420-second executor/client deadline; Telegram planning follows the requested recipient and attachment instead of the historical Saved Messages script.
- Focused schema, confirmation, audit, circuit-breaker, Sol routing, GUI-policy, and desktop-session handoff checks pass.
- No bare-metal file-management run or five-day reliability gate has been recorded, so `VISION_CHECKLIST.md` remains unchecked.

Remaining planned order:

- App launching, window management, long-running tasks.

## Frozen Scope

Until explicitly unfrozen, make bug fixes only in:

- Telegram gateway.
- DPDPA consent/compliance ledger.
- Fleet dashboard.
- Pinecone/ChromaDB overlap or duplication.

Do not add features to these areas while M3 integration is the priority.

## Actual Runtime Architecture

YantraOS is not currently the strict two-process system described in the README. The working implementation has several independent paths.

### Kriya Daemon

Entry points:

- `core/daemon.py`
- `core/engine.py`

The current loop implements:

```text
SENSE -> REASON -> ACT
```

`REMEMBER` and `LEARN` are vision concepts but are not active execution phases. ChromaDB exists, yet the main loop does not retrieve memory before reasoning or embed action outcomes after execution.

The daemon starts a FastAPI service on `127.0.0.1:50000`. It does not currently expose the documented `/run/yantra/ipc.sock` protocol.

### Standalone Natural-Language Action Path

Entry point:

- `core/yantra_core.py`

Flow:

```text
User instruction
  -> Azure OpenAI action classification
  -> confirmation
  -> foundry_action_bridge.py or computer_use_bridge.py
```

This is the path used during M2 testing. It is parallel to, not integrated into, the production Kriya Loop.

### Privileged Host Executor

Entry point:

- `core/host_executor.py`

Intended boundary:

```text
Typed JSON intent
  -> /run/yantra/executor.sock
  -> schema and target validation
  -> BTRFS pre-flight snapshot
  -> explicit argv command or approved external bridge
```

The executor rejects unknown intents, shell metacharacters, oversized payloads, and invalid action schemas. It uses explicit subprocess argument arrays rather than `shell=True` for normal privileged dispatch.

### Docker Sandbox

Entry point:

- `core/sandbox.py`

Healthy-mode controls include:

- No network.
- No host mounts.
- Read-only root filesystem.
- All capabilities dropped.
- `no-new-privileges`.
- Unprivileged `nobody` user.
- Memory, CPU, PID, timeout, image, shell, script, and environment limits.

### Other Processes

- `core/telegram_gateway.py`: separate Telegram service.
- `core/ipc_server.py`: localhost HTTP state/control API.
- `ui/shell.py`: Textual UI prototype.
- `ui/gui_shell.py`: accepted primary PySide6 Visual Intent Shell, connected to the privileged executor socket.
- `frontend_src/`: Vite/React frontend prototype.
- Cloud heartbeat and compliance components run as supporting subsystems.

## M2 Computer-Use Design

Primary file:

- `core/computer_use_bridge.py`

Action protocol:

```json
{"action":"click","x":100,"y":200,"button":"left"}
{"action":"type","text":"exact text"}
{"action":"key","key":"28:1 28:0"}
{"action":"wait","seconds":2}
{"action":"clipboard_copy"}
{"action":"clipboard_copy","text":"exact clipboard text"}
{"action":"clipboard_paste"}
{"action":"done","reason":"visually verified"}
```

Important behavior:

- `ydotool key` requires each press/release event as a separate argv item.
- Newline characters passed to `ydotool type` do not act as physical Enter keys.
- Use explicit key events for Enter.
- Use clipboard actions for URLs, exact copied values, Unicode, and multiline content.
- Absolute ydotool pointer movement collapses to the top-left under the current KDE/Wayland setup.
- The bridge resets the pointer to `(0,0)` and then applies calibrated relative movement.
- The screen-change threshold is configurable through `YANTRA_SCREEN_CHANGE_THRESHOLD`.
- Wait and clipboard-copy operations do not count as ineffective screen-changing actions.
- Two ineffective interactive outcomes stop the run rather than allowing an expensive loop.

Computer-use exit codes:

| Code | Meaning |
|---|---|
| `0` | Model declared the task complete |
| `1` | Execution or integration error |
| `2` | Step cap reached |
| `3` | Confirmation rejected or unavailable |
| `4` | Two interactive actions caused no visible change |

## Security Invariants

Future work must preserve these constraints:

- No raw privileged shell strings.
- Privileged operations use typed, allowlisted intents.
- Validate at every trust boundary, even when an upstream layer already validates.
- Use explicit subprocess argv arrays.
- Reject unknown fields and unknown actions.
- Fail closed if mandatory confirmation cannot run.
- Log proposed and executed external actions without logging secrets.
- Keep system-health generated scripts inside the hardened Docker path.
- Require BTRFS pre-flight checks for destructive host intents on installed systems.
- Preserve localhost-only binding for control endpoints unless an authenticated transport is deliberately designed.
- Never treat a model's `done` response as sufficient when the requested effect is not visibly verifiable.
- Do not publish posts, send messages, send email, accept purchases, or perform other external side effects unless the instruction explicitly authorizes that final action.

## Critical Risks and Contradictions

These are active engineering facts, not optional cleanup.

### Host Shell Fallback

`core/engine.py` executes LLM-generated scripts through `asyncio.create_subprocess_shell()` when Docker is unavailable. This contradicts the documented claim that LLM output never executes directly on the host.

Priority: critical. Replace this behavior with observe-only or fail-closed degradation before production use.

### M2 Bypasses the Full Host Chain

`core/yantra_core.py` launches bridges directly. It does not pass through the host executor's complete schema and snapshot path. M3 must reconcile this rather than maintaining two action systems.

### systemd Entry and Session Context

The deployed systemd entry still needs verification as a module entry point. Live M4 testing used `python -m core.host_executor`; the executor now drops computer-use bridge execution to the logged-in desktop account so Wayland, clipboard, Spectacle, and ydotool operate in the correct session.

### BTRFS Does Not Roll Back External Effects

Snapshots can protect filesystem state but cannot undo email, posts, messages, network requests, or clipboard actions. External effects require explicit confirmation and idempotency, not only snapshots.

### IPC Drift

Current transports disagree:

- README: `/run/yantra/ipc.sock`.
- Textual client: `/tmp/yantra.sock` or raw TCP.
- Active daemon: HTTP on `127.0.0.1:50000`.

The TUI is currently disconnected from the active daemon protocol.

### Model Routing Verification

Luna/Terra/Sol aliases and deployment defaults are implemented, but live deployment availability is unverified. Hardware status reporting and routing decisions still use inconsistent state names.

### Dependency and Build Drift

`requirements.txt` does not fully describe all imported runtime components. Playwright browser installation and desktop tools are not fully provisioned by the existing build manifests.

README build commands reference files that do not exist under the documented names. Verify paths before following historical setup instructions.

### Audit Limitations

Audit files are append-only by convention, not cryptographically immutable. Logging failures are not consistently fail-closed, and full instructions or typed text may expose sensitive content.

## Documentation Discrepancies

Do not repeat these claims without qualification:

- The active architecture is not strictly two processes.
- The daemon does not currently use the documented UNIX socket.
- The Kriya Loop does not implement active REMEMBER and LEARN phases.
- Pinecone is not an active runtime skill-store implementation in this tree.
- The TUI is not currently connected to the daemon.
- The frontend expects streaming behavior not supplied by the current API.
- The README mixes v0.2.4 and v1.0 Alpha RC2 status language.
- Several claimed systemd hardening settings are commented out.
- External desktop actions necessarily operate outside the Docker sandbox.

## Repository State

At the time of this memory update:

- Branch: `main`, aligned with `origin/main` before local working changes.
- Baseline tag: `v0.2.4-ops-agent-baseline`.
- M1/M2 files and tests are uncommitted or modified in the working tree.
- Do not discard or revert these changes.
- `SCOPE_FREEZE.md` and `VISION_CHECKLIST.md` are untracked.
- Runtime secrets and local state are ignored; never add them to Git.

Important M1/M2 files:

- `core/action_confirmation.py`
- `core/audit_log.py`
- `core/computer_use_bridge.py`
- `core/foundry_action_bridge.py`
- `core/host_executor.py`
- `core/yantra_core.py`
- `test_computer_use_bridge.py`
- `test_external_action.py`
- `test_m1_bridge.py`
- `test_m2_core.py`

## Test Evidence and Practice

Focused tests known to exist:

- `test_external_action.py`: typed external-action validation, snapshot gating, live-ISO blocking, audit phases, and rejection cases. Several integration boundaries are mocked.
- `test_computer_use_bridge.py`: screenshot difference, ineffective-action counting, and clipboard command construction.
- `test_m1_bridge.py`: manual real-action smoke script.
- `test_m2_core.py`: manual live Azure/browser script, not a deterministic unit test.

The focused computer-use tests passed on 2026-07-13:

```text
Ran 6 tests
OK
```

Do not run every root `test_*.py` blindly. Some modules perform live Azure operations at import time, and manual M1/M2 scripts can open browsers or write files.

Safe focused verification:

```bash
venv/bin/python -m unittest test_computer_use_bridge.py
venv/bin/python -m py_compile core/computer_use_bridge.py core/yantra_core.py
venv/bin/python -m pytest -p no:cacheprovider test_external_action.py
```

Real GUI testing requires the active desktop session and:

```bash
export YDOTOOL_SOCKET=/tmp/.ydotool_socket
export YDOTOOL_POINTER_SCALE=2.0
```

## Development Entry Points

From the repository root:

```bash
source venv/bin/activate
python -m core.daemon
python -m core.yantra_core "your instruction"
python -m ui.shell
python -m ui.gui_shell
```

The TUI command starts the prototype, but its transport currently does not match the active daemon.

Read-only diagnostics:

```bash
git status --short --branch
git describe --tags --always --dirty
systemctl status yantra.service yantra-host-executor.service yantra-telegram.service
curl http://127.0.0.1:50000/health
curl http://127.0.0.1:50000/state
curl http://127.0.0.1:50000/debug
```

## M3 Recommended Execution Order

1. Remove the direct host-shell fallback when Docker is unavailable.
2. Define one typed `EXTERNAL_ACTION` schema shared by engine, executor, and bridges.
3. Route EXTERNAL_ACTION from the production ACT phase with `action_payload` intact.
4. Preserve Docker routing for system-health scripts.
5. Design a user-session action service for Wayland automation instead of running GUI tools as root.
6. Consolidate confirmation counters and audit paths into durable system locations.
7. Ensure one confirmation boundary per action and support non-interactive service operation safely.
8. Route Luna, Terra, and Sol according to the July roadmap.
9. Apply one five-consecutive-failure circuit breaker across sandbox and external actions.
10. Add integration tests for the engine-to-executor-to-session-action path.
11. Reconcile IPC and choose one supported TUI transport.
12. Update README, checklist, dependency manifests, systemd units, and build commands to match reality.

## Rules for Future Agents

- Read this file, the execution roadmap, scope freeze, and relevant code before editing.
- Treat M2 and M4 as complete. Proceed to M5 while preserving explicit remaining M3 cleanup items.
- Preserve unrelated working-tree changes.
- Do not expand frozen subsystems.
- Prefer the smallest correct change.
- Do not add backward compatibility without a concrete consumer or persisted-data need.
- Never expose or commit API keys, tokens, private keys, consent databases, or local environment files.
- Do not claim a capability is verified solely because a model produced code for it.
- Separate code-complete, integration-complete, and reliability-complete status.
- For external side effects, default to draft/preview unless the instruction explicitly authorizes final submission.
- Keep action payloads typed and reject unknown fields.
- Add focused deterministic tests before live-system tests.
- Record real M3 acceptance evidence in the repository rather than relying only on terminal history.

## Maintenance Protocol

Update this file when:

- Project authority changes milestone status.
- A major architecture path is added, removed, or unified.
- A security invariant changes.
- A discrepancy listed here is fixed.
- A real reliability gate is completed.
- Operational commands or required environment variables change.

When updating it:

1. Change the date.
2. Cite current file paths.
3. Move resolved risks out of the active-risk section.
4. Keep milestone authority separate from stale checklist state.
5. Never place secrets or personal data in this file.
