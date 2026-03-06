"""
YantraOS TUI Shell — core/tui_shell.py
Phase 2: Reactive Widgets + Async IPC Bridge
Geometric Law: zero rounded corners, strict hex palette.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog, Input, Static

# ── Palette ──────────────────────────────────────────────────────────────────
BG          = "#121212"
BORDER_CLR  = "#00E5FF"
ACCENT_DIM  = "#888888"
TEXT_BRIGHT = "#E0E0E0"
GREEN       = "#00FF85"
AMBER       = "#FFB000"
RED         = "#FF3B30"

# ── IPC constants ─────────────────────────────────────────────────────────────
UDS_PATH        = "/run/yantra/ipc.sock"
POLL_INTERVAL   = 2.0          # seconds between telemetry polls
RECONNECT_DELAY = 3.0          # seconds to wait before retry
MAX_LOG_LINES   = 500


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — raw HTTP over UDS
# ─────────────────────────────────────────────────────────────────────────────

def _uds_get(path: str, timeout: float = 5.0) -> dict[str, Any]:
    """
    Synchronous HTTP/1.0 GET over UDS.
    Called from the worker thread so that asyncio's event loop is never blocked.
    """
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(UDS_PATH)
        request = f"GET {path} HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode())

        raw = b""
        while chunk := sock.recv(4096):
            raw += chunk

    # Strip HTTP headers, parse JSON body
    _, _, body = raw.partition(b"\r\n\r\n")
    return json.loads(body.decode())


def _build_bar(pct: float, width: int = 18) -> str:
    """Return an ANSI-styled ASCII progress bar string (for Rich markup)."""
    filled   = int(pct / 100 * width)
    empty    = width - filled
    color    = GREEN if pct < 75 else (AMBER if pct < 90 else RED)
    bar_body = f"[{color}]{'█' * filled}[/][{ACCENT_DIM}]{'░' * empty}[/]"
    return f"[{BORDER_CLR}][[/]{bar_body}[{BORDER_CLR}]][/]"


# ─────────────────────────────────────────────────────────────────────────────
# GPUHealth Widget — reactive left pane
# ─────────────────────────────────────────────────────────────────────────────

class GPUHealth(Widget):
    """
    Reactive telemetry widget.
    Reads from reactive attributes; Textual re-renders automatically when they change.
    """

    phase:     reactive[str]   = reactive("OFFLINE")
    iteration: reactive[int]   = reactive(0)
    vram_used: reactive[float] = reactive(0.0)
    vram_tot:  reactive[float] = reactive(0.0)
    gpu_util:  reactive[float] = reactive(0.0)
    cpu_pct:   reactive[float] = reactive(0.0)
    disk_free: reactive[float] = reactive(0.0)
    model:     reactive[str]   = reactive("—")
    routing:   reactive[str]   = reactive("LOCAL")
    connected: reactive[bool]  = reactive(False)

    DEFAULT_CSS = f"""
    GPUHealth {{
        background: {BG};
        border: solid {BORDER_CLR};
        padding: 1 2;
        color: {TEXT_BRIGHT};
    }}
    """

    def render(self) -> str:                            # type: ignore[override]
        vram_pct   = (self.vram_used / self.vram_tot * 100) if self.vram_tot else 0.0
        vbar       = _build_bar(vram_pct)
        cbar       = _build_bar(self.cpu_pct)
        gbar       = _build_bar(self.gpu_util)
        dot        = f"[{GREEN}]●[/]" if self.connected else f"[{AMBER}]○[/]"
        status_lbl = f"[{GREEN}]LIVE[/]"   if self.connected else f"[{AMBER}]AWAITING DAEMON[/]"
        phase_col  = BORDER_CLR if self.connected else AMBER

        return (
            f"[bold {BORDER_CLR}]╔═  TELEMETRY  ═════════════════════╗[/]\n\n"
            f"  [{ACCENT_DIM}]DAEMON  [/]  {dot}  {status_lbl}\n"
            f"  [{ACCENT_DIM}]SOCKET  [/]  [{ACCENT_DIM}]{UDS_PATH}[/]\n\n"
            f"  [{ACCENT_DIM}]PHASE   [/]  [bold {phase_col}]{self.phase}[/]\n"
            f"  [{ACCENT_DIM}]ITER    [/]  [{TEXT_BRIGHT}]{self.iteration:,}[/]\n"
            f"  [{ACCENT_DIM}]MODEL   [/]  [{TEXT_BRIGHT}]{self.model}[/]\n"
            f"  [{ACCENT_DIM}]ROUTE   [/]  [{TEXT_BRIGHT}]{self.routing}[/]\n\n"
            f"  [{ACCENT_DIM}]VRAM    [/]  {vbar}\n"
            f"  [{ACCENT_DIM}]        [/]  [{TEXT_BRIGHT}]{self.vram_used:.1f}[/]"
            f"[{ACCENT_DIM}] / {self.vram_tot:.1f} GB[/]"
            f"  [{ACCENT_DIM}]({vram_pct:.0f}%)[/]\n\n"
            f"  [{ACCENT_DIM}]GPU     [/]  {gbar}  [{TEXT_BRIGHT}]{self.gpu_util:.0f}%[/]\n"
            f"  [{ACCENT_DIM}]CPU     [/]  {cbar}  [{TEXT_BRIGHT}]{self.cpu_pct:.0f}%[/]\n"
            f"  [{ACCENT_DIM}]DISK    [/]  [{TEXT_BRIGHT}]{self.disk_free:.1f} GB free[/]\n\n"
            f"[bold {BORDER_CLR}]╚═══════════════════════════════════╝[/]"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────

class YantraShell(App):
    """YantraOS Geometric TUI Shell — Phase 2: Reactive Widgets + IPC Bridge."""

    TITLE = "YantraOS  //  Kriya Loop Interface"

    CSS = f"""
    Screen {{
        background: {BG};
        layout: grid;
        grid-size: 10;
        grid-rows: 3 1fr 3;
    }}

    /* ── Header ── */
    #header {{
        column-span: 10;
        height: 3;
        background: {BG};
        border-bottom: solid {BORDER_CLR};
        color: {BORDER_CLR};
        content-align: center middle;
        text-style: bold;
    }}

    /* ── Left pane: Telemetry (30%) ── */
    GPUHealth {{
        column-span: 3;
        background: {BG};
    }}

    /* ── Right pane: ThoughtStream (70%) ── */
    #pane-thoughtstream {{
        column-span: 7;
        background: {BG};
        border: solid {BORDER_CLR};
        padding: 0 1;
    }}

    /* ── Bottom: Input prompt ── */
    #pane-prompt {{
        column-span: 10;
        height: 3;
        background: {BG};
        border-top: solid {BORDER_CLR};
        layout: horizontal;
    }}

    #prompt-label {{
        width: auto;
        height: 3;
        content-align: left middle;
        color: {BORDER_CLR};
        padding: 0 1;
    }}

    #prompt-input {{
        height: 3;
        background: {BG};
        color: {TEXT_BRIGHT};
        border: none;
    }}

    #prompt-input:focus {{
        border: none;
    }}

    RichLog {{
        background: {BG};
        color: {TEXT_BRIGHT};
        scrollbar-color: {BORDER_CLR};
        scrollbar-background: {BG};
    }}
    """

    BINDINGS = [
        ("ctrl+c", "quit",         "Quit"),
        ("ctrl+r", "force_refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        # ── Header ──
        yield Static(
            f"[bold {BORDER_CLR}]◈  YANTRAOS[/]  "
            f"[{ACCENT_DIM}]//  Kriya Loop Interface  //  v0.2.0[/]",
            id="header",
        )

        # ── Left: GPUHealth widget ──
        yield GPUHealth()

        # ── Right: ThoughtStream log ──
        log = RichLog(id="pane-thoughtstream", highlight=True, markup=True)
        log.border_title = "THOUGHTSTREAM"
        yield log

        # ── Bottom: Input prompt ──
        with Horizontal(id="pane-prompt"):
            yield Static(f"[bold {BORDER_CLR}]▸[/]", id="prompt-label")
            yield Input(
                placeholder="  Send command to Kriya daemon…",
                id="prompt-input",
            )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._poll_telemetry()   # kick off the worker loop
        self._stream_logs()      # kick off the SSE stream worker

    # ── Telemetry polling worker (thread-based) ───────────────────────────────

    @work(thread=True, exclusive=True, name="telemetry-poll")
    def _poll_telemetry(self) -> None:
        """
        Runs in a background thread.
        Polls /telemetry every POLL_INTERVAL seconds and mutates reactive attrs.
        Gracefully handles ConnectionRefusedError / socket errors.
        """
        gpu  = self.query_one(GPUHealth)
        log  = self.query_one("#pane-thoughtstream", RichLog)

        while not self.app.is_running is False:
            try:
                data    = _uds_get("/telemetry")
                phase   = str(data.get("phase", "UNKNOWN")).upper()
                # Strip enum prefix if present (e.g. "KriyaPhase.SENSE" → "SENSE")
                if "." in phase:
                    phase = phase.split(".")[-1]

                self.app.call_from_thread(
                    self._apply_telemetry,
                    phase,
                    int(data.get("iteration", 0)),
                    float(data.get("vram_used_gb",  0.0)),
                    float(data.get("vram_total_gb", 0.0)),
                    float(data.get("gpu_util_pct",  0.0)),
                    float(data.get("cpu_pct",       0.0)),
                    float(data.get("disk_free_gb",  0.0)),
                    str(data.get("active_model",       "—")),
                    str(data.get("inference_routing", "LOCAL")),
                )

            except (ConnectionRefusedError, FileNotFoundError, OSError):
                self.app.call_from_thread(self._set_offline)
                time.sleep(RECONNECT_DELAY)
                continue

            except Exception as exc:  # noqa: BLE001
                self.app.call_from_thread(
                    log.write,
                    f"[{AMBER}][WARN] Telemetry parse error: {exc}[/]",
                )

            time.sleep(POLL_INTERVAL)

    def _apply_telemetry(
        self,
        phase: str, iteration: int,
        vram_used: float, vram_tot: float,
        gpu_util: float, cpu_pct: float, disk_free: float,
        model: str, routing: str,
    ) -> None:
        gpu = self.query_one(GPUHealth)
        gpu.connected = True
        gpu.phase     = phase
        gpu.iteration = iteration
        gpu.vram_used = vram_used
        gpu.vram_tot  = vram_tot
        gpu.gpu_util  = gpu_util
        gpu.cpu_pct   = cpu_pct
        gpu.disk_free = disk_free
        gpu.model     = model
        gpu.routing   = routing

    def _set_offline(self) -> None:
        gpu = self.query_one(GPUHealth)
        gpu.connected = False
        gpu.phase     = "OFFLINE"
        log = self.query_one("#pane-thoughtstream", RichLog)
        log.write(
            f"[{AMBER}][{time.strftime('%H:%M:%S')}]  "
            f"AWAITING DAEMON CONNECTION…  {UDS_PATH}[/]"
        )

    # ── SSE ThoughtStream streaming worker ────────────────────────────────────

    @work(thread=True, exclusive=True, name="stream-logs")
    def _stream_logs(self) -> None:
        """
        Connects to the daemon's /stream SSE endpoint over UDS.
        Parses `data: {...}` lines and writes log entries to RichLog.
        Retries on disconnect.
        """
        log = self.query_one("#pane-thoughtstream", RichLog)

        while True:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(30.0)
                    sock.connect(UDS_PATH)
                    req = (
                        "GET /stream HTTP/1.0\r\n"
                        "Host: localhost\r\n"
                        "Accept: text/event-stream\r\n"
                        "Connection: keep-alive\r\n\r\n"
                    )
                    sock.sendall(req.encode())

                    # Skip HTTP headers
                    buf = b""
                    while b"\r\n\r\n" not in buf:
                        chunk = sock.recv(256)
                        if not chunk:
                            break
                        buf += chunk
                    # Any surplus after headers belongs to the SSE body
                    _, _, remainder = buf.partition(b"\r\n\r\n")

                    line_buf = remainder.decode(errors="replace")
                    while True:
                        raw_chunk = sock.recv(4096)
                        if not raw_chunk:
                            break
                        line_buf += raw_chunk.decode(errors="replace")
                        while "\n" in line_buf:
                            line, line_buf = line_buf.split("\n", 1)
                            line = line.strip()
                            if line.startswith("data:"):
                                json_part = line[5:].strip()
                                if not json_part or json_part == ":keepalive":
                                    continue
                                try:
                                    evt = json.loads(json_part)
                                    msg = evt.get("log", "")
                                    if msg:
                                        ts  = time.strftime("%H:%M:%S")
                                        self.app.call_from_thread(
                                            log.write,
                                            f"[{ACCENT_DIM}]{ts}[/]  [{TEXT_BRIGHT}]{msg}[/]",
                                        )
                                except json.JSONDecodeError:
                                    pass

            except (ConnectionRefusedError, FileNotFoundError, OSError):
                time.sleep(RECONNECT_DELAY)
                continue
            except Exception:  # noqa: BLE001
                time.sleep(RECONNECT_DELAY)
                continue

    # ── Input submission ──────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Dispatch a command to the daemon when user hits Enter."""
        raw = event.value.strip()
        event.input.clear()
        if not raw:
            return
        log = self.query_one("#pane-thoughtstream", RichLog)
        log.write(f"[{BORDER_CLR}]▸  CMD:[/]  [{TEXT_BRIGHT}]{raw}[/]")
        self._dispatch_command(raw)

    @work(thread=True, name="cmd-dispatch")
    def _dispatch_command(self, raw: str) -> None:
        log = self.query_one("#pane-thoughtstream", RichLog)
        try:
            # Split on first space: first token = action, rest = text payload.
            # e.g. "inject_thought Turn on battery saver"
            #   -> action = "inject_thought", text = "Turn on battery saver"
            parts  = raw.split(None, 1)
            action = parts[0] if parts else raw
            payload: dict[str, str] = {"action": action}
            if len(parts) > 1:
                payload["text"] = parts[1]
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(5.0)
                sock.connect(UDS_PATH)
                body    = json.dumps(payload).encode()
                headers = (
                    "POST /command HTTP/1.0\r\n"
                    "Host: localhost\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "Connection: close\r\n\r\n"
                )
                sock.sendall(headers.encode() + body)
                raw_resp = b""
                while chunk := sock.recv(4096):
                    raw_resp += chunk
            _, _, resp_body = raw_resp.partition(b"\r\n\r\n")
            resp = json.loads(resp_body.decode())
            self.app.call_from_thread(
                log.write,
                f"[{GREEN}]◀  {json.dumps(resp)}[/]",
            )
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            self.app.call_from_thread(
                log.write,
                f"[{AMBER}][WARN] Daemon not reachable — command dropped.[/]",
            )
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                log.write,
                f"[{RED}][ERR] Command failed: {exc}[/]",
            )

    # ── Actions ───────────────────────────────────────────────────────────────

    async def action_quit(self) -> None:
        self.exit()

    async def action_force_refresh(self) -> None:
        self._poll_telemetry()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    YantraShell().run()
