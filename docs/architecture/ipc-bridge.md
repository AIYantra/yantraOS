# IPC Bridge & UNIX Sockets

In YantraOS, the Kriya Loop (`yantra.service`) operates in complete isolation from user interfaces such as the Textual TUI Shell (`tui_shell.py`) and the Web HUD (`/api/telemetry/ingest`).

The mechanism that binds these distinct components together is the **IPC Bridge** running over a purely asynchronous UNIX Domain Socket.

## Strict Decoupling

The paradigm of decoupled execution enforces the safety of the OS. The Yantra Daemon and the TUI **share absolutely no memory**.

1. Handing raw execution logic over to the TUI process is a security hazard; GUI/CLI abstractions can crash, freeze, or block UI rendering loops.
2. Conversely, the Kriya Loop runs 24/7. It cannot be halted because a user killed the terminal window. A detached daemon guarantees OS continuity.

## The UNIX Domain Socket (/run/yantra/ipc.sock)

Communication occurs natively on Linux via the `/run/yantra/ipc.sock` socket.

When the Yantra Shell is opened, it connects as a stateless, read-only consumer:

### Daemon Dispatch (Provider)

The daemon emits its state in real-time as a serialized JSON byte stream matching the `yantraos/telemetry/v1` schema.

```json
{
  "$schema": "yantraos/telemetry/v1",
  "timestamp": "2026-03-23T14:48:00Z",
  "daemon_status": "ACTIVE",
  "active_model": "llama3:8b",
  "vram_usage": {
    "used_gb": 4.1,
    "total_gb": 16.0,
    "percent": 25.6
  },
  "inference_routing": "LOCAL",
  "current_cycle": {
    "phase": "REASON",
    "iteration": 1045,
    "log_tail": ["> REASONING: Optimizing workflow..."]
  }
}
```

### Yantra Shell Shell (Consumer)

The TUI reads the stream dynamically, piping the VRAM metrics into the React-like `GPUHealth` component, and updating the scrolling `ThoughtStream` log.

Should the TUI crash, the JSON stream continues unimpeded over the socket. Should the daemon crash, the TUI simply logs "UNIX Socket Disconnected: Attempting Reconnect..." and waits gracefully.

### Mathematical Prohibition of Shared Memory

Memory sharing is "mathematically prohibited" in YantraOS because the architecture of the `asyncio` loop strictly forbids cross-process memory (`multiprocessing.Value` or `mmap`) without incurring severe security synchronization overheads or breaking the non-blocking I/O requirement. Serialized IPC forces all data crossing the boundary to be structurally validated against a zero-trust schema before ingestion.
