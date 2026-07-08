# The Kriya Loop

The Kriya Loop is the heartbeat of YantraOS — a persistently running asynchronous Python 3.12 daemon (`yantra.service`) that functions as the operating system's core orchestration layer. It never sleeps, and by design, it never hard-crashes.

## The Architecture of Autonomy

Operating natively as a `systemd` background daemon, the Kriya Loop serves to solve the "Dead OS Crisis"—the paradigm where operating systems are passive entities awaiting human input. YantraOS reverses this: the environment operates as an autonomous, self-healing entity executing a relentless 4-phase cycle:

```text
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌────────────────────┐
│ ANALYZE  │ →  │  PATCH   │ →  │   TEST   │ →  │ UPDATE_ARCHITECTURE│
└──────────┘    └──────────┘    └──────────┘    └────────────────────┘
```

The underlying principle is **The Karma Yogi**: to act without attachment to outcome. If an exception occurs, or a sandbox execution fails, the daemon logs the failure, updates its internal context, and simply proceeds to the next cycle. Unhandled exceptions are routed to `/var/log/yantra/engine.log`, isolating the daemon from fatal collapse.

## Strict Decoupling

The Kriya Daemon shares absolutely **no memory** with its interfaces.

### IPC Bridge (UNIX Domain Socket)

Communication between the daemon and its clients (whether the local Textual TUI Shell or the Web HUD telemetry ingester) occurs exclusively over a UNIX Domain Socket at `/run/yantra/ipc.sock`.

- **Format:** Structured JSON streams (`yantraos/telemetry/v1`).
- **Nature:** Non-blocking asynchronous I/O. The `asyncio` event loop is strictly guarded against synchronous blocking operations.
- **Client Side:** The TUI and Web dashboards act as purely stateless consumers mirroring the daemon's internal stream.

## Priority Interrupts

While the Kriya Loop is continuously executing its autonomous background mission (the "CRITICAL PRIMARY DIRECTIVE"), operators can inject real-time priority tasks via the IPC bridge (e.g., through the Telegram Gateway).

When a priority task is injected, the Kriya Loop triggers a **Cognitive Override**:
1. **Context Wiping:** It temporarily wipes the LLM's conversation history to guarantee it is not distracted by past autonomous thoughts.
2. **Prompt Isolation:** It completely strips out the background mission from the system prompt, enforcing a singular focus on executing the user's task.
3. **Execution & Retry:** The task is executed and immediately pushed out via asynchronous notification. If the task fails, the engine escalates the error back into the LLM context and automatically retries the operation up to 3 times before falling back to its background mission.

## Execution Constraints: Prohibition by Omission

When the `ACT` phase generates an execution blueprint, that code is securely routed to the Ephemeral Docker Sandbox (`core/sandbox.py`). The daemon running on the host never calls `os.system` or `subprocess` directly, unless orchestrating whitelisted BTRFS snapshot operations governed strictly by Polkit rules.

This strict boundary enforces memory isolation, hardware stability, and security across the local network—allowing YantraOS to function as the world's first true Level 3 Agentic OS.
