"""
YantraOS — Mission Control TUI Shell  (core/tui_shell.py)
Phase 3: Cyberpunk Dashboard — "Electric Blue Overseer"

Layout (grid 12 cols × 4 rows):
  ┌──────────────────────────────────────────────────┐
  │                    HEADER BAR                    │  row 0 (3 rows tall)
  ├────────────┬────────────────────┬────────────────┤
  │  TELEMETRY │   THOUGHTSTREAM    │    CONTROLS    │  row 1 (fills)
  │  (gauges)  │   (SSE log feed)   │  (cmd palette) │
  ├────────────┴────────────────────┴────────────────┤
  │            COMMAND BAR  (input + buttons)         │  row 2 (3 rows tall)
  └──────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
import threading
from typing import Any

from textual import work, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Container
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    Button,
    Input,
    RichLog,
    Static,
    Label,
)
from rich.text import Text
from rich.panel import Panel
from rich.align import Align

# ── Colour Palette ────────────────────────────────────────────────────────────
# "Electric Blue Overseer" — void black + cyan + acid green + amber + crimson
BG           = "#0A0E17"      # void black
BG_MID       = "#0D1220"      # slightly lighter panels
CYBER_CYAN   = "#00E5FF"      # primary accent — electric blue
ACID_GREEN   = "#39FF14"      # live indicators, low-load bars
AMBER        = "#FFB000"      # warnings, medium load
CRIMSON      = "#FF2D55"      # critical alerts, high load
TEXT_BRIGHT  = "#E8EAF0"      # primary text
TEXT_DIM     = "#4A5568"      # secondary / timestamps
HEADER_GLOW  = "#1DE9B6"      # teal-mint for header accent
BORDER_DIM   = "#1A2744"      # subtle panel borders
PHASE_SENSE  = "#00E5FF"      # cyan
PHASE_REASON = "#BF5AF2"      # electric violet
PHASE_ACT    = "#39FF14"      # acid green
PHASE_REM    = "#FFB000"      # amber
PHASE_PATCH  = "#FF6B35"      # orange
PHASE_UPDATE = "#1DE9B6"      # teal
PHASE_OTHER  = "#4A5568"      # dim grey

# ── IPC ───────────────────────────────────────────────────────────────────────
UDS_PATH        = "/run/yantra/ipc.sock"
POLL_INTERVAL   = 2.0
RECONNECT_DELAY = 3.0
MAX_LOG_LINES   = 600


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uds_get(path: str, timeout: float = 5.0) -> dict[str, Any]:
    """Synchronous HTTP/1.0 GET over UDS (called from worker thread)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(UDS_PATH)
        sock.sendall(
            f"GET {path} HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            .encode()
        )
        raw = b""
        while chunk := sock.recv(4096):
            raw += chunk
    _, _, body = raw.partition(b"\r\n\r\n")
    return json.loads(body.decode())


def _uds_post(path: str, body: dict, timeout: float = 5.0) -> dict[str, Any]:
    """Synchronous HTTP/1.0 POST over UDS (called from worker thread)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(UDS_PATH)
        payload = json.dumps(body).encode()
        headers = (
            f"POST {path} HTTP/1.0\r\n"
            "Host: localhost\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        sock.sendall(headers + payload)
        raw = b""
        while chunk := sock.recv(4096):
            raw += chunk
    _, _, resp_body = raw.partition(b"\r\n\r\n")
    return json.loads(resp_body.decode())


def _gauge(
    pct: float,
    width: int = 20,
    low_col: str = ACID_GREEN,
    mid_col: str = AMBER,
    hi_col: str = CRIMSON,
) -> str:
    """Build a Rich-markup ASCII gauge bar."""
    pct = max(0.0, min(100.0, pct))
    filled = int(pct / 100 * width)
    empty  = width - filled
    if pct < 60:
        color = low_col
        sym   = "▰"
    elif pct < 85:
        color = mid_col
        sym   = "▰"
    else:
        color = hi_col
        sym   = "▰"
    bar = f"[{color}]{sym * filled}[/][{TEXT_DIM}]{'▱' * empty}[/]"
    return f"[{CYBER_CYAN}][[/]{bar}[{CYBER_CYAN}]][/]"


def _phase_color(phase: str) -> str:
    p = phase.upper()
    if "SENSE"  in p: return PHASE_SENSE
    if "REASON" in p: return PHASE_REASON
    if "ACT"    in p: return PHASE_ACT
    if "REMEMB" in p: return PHASE_REM
    if "PATCH"  in p: return PHASE_PATCH
    if "UPDATE" in p: return PHASE_UPDATE
    return PHASE_OTHER


def _colorize_log(msg: str) -> str:
    """Apply phase-based colour to a ThoughtStream message."""
    u = msg.upper()
    if "[SENSE]"  in u or "TELEMETRY" in u: col = PHASE_SENSE
    elif "[REASON]" in u or "REASONING" in u: col = PHASE_REASON
    elif "[ACT]"    in u or "ACTION"    in u: col = PHASE_ACT
    elif "[REMEMBER]" in u or "MEMORY"  in u: col = PHASE_REM
    elif "[PATCH]"  in u or "CLOUD"     in u: col = PHASE_PATCH
    elif "[UPDATE]" in u or "TELEMETRY" in u: col = PHASE_UPDATE
    elif "ERROR"    in u or "FAIL"       in u: col = CRIMSON
    elif "WARN"     in u: col = AMBER
    elif "INJECT"   in u: col = HEADER_GLOW
    elif "PAUSED"   in u: col = AMBER
    elif "RESUMED"  in u: col = ACID_GREEN
    elif "SYSTEM"   in u or "DAEMON"     in u: col = TEXT_BRIGHT
    else: col = TEXT_DIM
    return f"[{col}]{msg}[/]"


# ── Header Widget ─────────────────────────────────────────────────────────────

class YantraHeader(Static):
    """Animated mission-control title bar."""

    connected: reactive[bool]  = reactive(False)
    paused:    reactive[bool]  = reactive(False)
    uptime:    reactive[float] = reactive(0.0)
    iteration: reactive[int]   = reactive(0)

    DEFAULT_CSS = f"""
    YantraHeader {{
        height: 3;
        background: {BG};
        border-bottom: solid {CYBER_CYAN};
        color: {CYBER_CYAN};
        content-align: center middle;
    }}
    """

    def on_mount(self) -> None:
        self._birth = time.monotonic()
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self.uptime = time.monotonic() - self._birth
        self.refresh()

    def render(self) -> Text:  # type: ignore[override]
        dot    = "●" if self.connected else "○"
        dot_c  = ACID_GREEN if self.connected else AMBER
        state  = "PAUSED" if self.paused else ("LIVE" if self.connected else "AWAIT")
        s_col  = AMBER if self.paused else (ACID_GREEN if self.connected else AMBER)
        hrs    = int(self.uptime // 3600)
        mins   = int((self.uptime % 3600) // 60)
        secs   = int(self.uptime % 60)
        up_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        t = Text(justify="center")
        t.append("◈  ", style=f"{CYBER_CYAN} bold")
        t.append("YANTRA", style=f"{CYBER_CYAN} bold")
        t.append("OS", style=f"{HEADER_GLOW} bold")
        t.append("  //  KRIYA LOOP OVERSEER  //  v0.3.0", style=f"{TEXT_DIM}")
        t.append("   ", style="")
        t.append(dot, style=f"{dot_c} bold")
        t.append(f" {state}", style=f"{s_col} bold")
        t.append(f"   iter: ", style=f"{TEXT_DIM}")
        t.append(f"#{self.iteration:,}", style=f"{TEXT_BRIGHT} bold")
        t.append(f"   up: {up_str}", style=f"{TEXT_DIM}")
        return t


# ── Telemetry Panel ───────────────────────────────────────────────────────────

class TelemetryPanel(Widget):
    """
    Left column — live hardware gauges and daemon state.
    Reactive attrs are mutated by the polling worker.
    """

    phase:       reactive[str]   = reactive("──────")
    iteration:   reactive[int]   = reactive(0)
    vram_used:   reactive[float] = reactive(0.0)
    vram_tot:    reactive[float] = reactive(0.0)
    gpu_util:    reactive[float] = reactive(0.0)
    cpu_pct:     reactive[float] = reactive(0.0)
    disk_free:   reactive[float] = reactive(0.0)
    model:       reactive[str]   = reactive("—")
    routing:     reactive[str]   = reactive("LOCAL")
    connected:   reactive[bool]  = reactive(False)
    is_paused:   reactive[bool]  = reactive(False)

    DEFAULT_CSS = f"""
    TelemetryPanel {{
        column-span: 3;
        background: {BG_MID};
        border: solid {CYBER_CYAN};
        padding: 1 2;
        color: {TEXT_BRIGHT};
    }}
    """

    def render(self) -> str:  # type: ignore[override]
        vram_pct   = (self.vram_used / self.vram_tot * 100) if self.vram_tot > 0 else 0.0
        vbar       = _gauge(vram_pct)
        cbar       = _gauge(self.cpu_pct)
        gbar       = _gauge(self.gpu_util)
        dbar       = _gauge(max(0, 100 - self.disk_free * 5))  # invert: used space

        dot        = f"[{ACID_GREEN} bold]●[/]" if self.connected else f"[{AMBER}]○[/]"
        status_lbl = (
            f"[{AMBER} bold]⏸  PAUSED[/]"   if self.is_paused and self.connected else
            f"[{ACID_GREEN} bold]▶  LIVE[/]" if self.connected else
            f"[{AMBER}]AWAITING…[/]"
        )
        phase_col = _phase_color(self.phase)
        disk_col  = ACID_GREEN if self.disk_free > 10 else (AMBER if self.disk_free > 3 else CRIMSON)

        sep = f"[{BORDER_DIM}]{'─' * 34}[/]"

        return (
            f"[bold {CYBER_CYAN}]╔  TELEMETRY  ═════════════════════╗[/]\n\n"
            f"  [{TEXT_DIM}]DAEMON  [/]  {dot}  {status_lbl}\n"
            f"  [{TEXT_DIM}]SOCKET  [/]  [{TEXT_DIM}]{UDS_PATH}[/]\n\n"
            f"{sep}\n\n"
            f"  [{TEXT_DIM}]PHASE   [/]  [bold {phase_col}]{self.phase}[/]\n"
            f"  [{TEXT_DIM}]ITER    [/]  [{TEXT_BRIGHT} bold]{self.iteration:,}[/]\n"
            f"  [{TEXT_DIM}]MODEL   [/]  [{HEADER_GLOW}]{self.model}[/]\n"
            f"  [{TEXT_DIM}]ROUTE   [/]  [{CYBER_CYAN}]{self.routing}[/]\n\n"
            f"{sep}\n\n"
            f"  [{TEXT_DIM}]VRAM    [/]  {vbar}\n"
            f"  [{TEXT_DIM}]        [/]  [{TEXT_BRIGHT}]{self.vram_used:.1f}[/]"
            f"[{TEXT_DIM}]/{self.vram_tot:.1f} GB  ({vram_pct:.0f}%)[/]\n\n"
            f"  [{TEXT_DIM}]GPU     [/]  {gbar}  [{TEXT_BRIGHT}]{self.gpu_util:.0f}%[/]\n"
            f"  [{TEXT_DIM}]CPU     [/]  {cbar}  [{TEXT_BRIGHT}]{self.cpu_pct:.0f}%[/]\n\n"
            f"{sep}\n\n"
            f"  [{TEXT_DIM}]DISK    [/]  [{disk_col}]{self.disk_free:.1f} GB free[/]\n\n"
            f"[bold {CYBER_CYAN}]╚═══════════════════════════════════╝[/]"
        )


# ── Control Panel ─────────────────────────────────────────────────────────────

class ControlPanel(Widget):
    """
    Right column — quick-action buttons and live status summary.
    Buttons POST to the IPC server directly from a thread worker.
    """

    is_paused:  reactive[bool] = reactive(False)
    connected:  reactive[bool] = reactive(False)
    last_resp:  reactive[str]  = reactive("—")

    DEFAULT_CSS = f"""
    ControlPanel {{
        column-span: 3;
        background: {BG_MID};
        border: solid {CYBER_CYAN};
        padding: 1 2;
        color: {TEXT_BRIGHT};
    }}
    Button {{
        width: 100%;
        margin-bottom: 1;
        background: {BG};
        color: {CYBER_CYAN};
        border: tall {CYBER_CYAN};
    }}
    Button:hover {{
        background: {CYBER_CYAN};
        color: {BG};
    }}
    Button.danger {{
        border: tall {CRIMSON};
        color: {CRIMSON};
    }}
    Button.danger:hover {{
        background: {CRIMSON};
        color: {BG};
    }}
    Button.active {{
        border: tall {ACID_GREEN};
        color: {ACID_GREEN};
    }}
    Button.active:hover {{
        background: {ACID_GREEN};
        color: {BG};
    }}
    Button.warn {{
        border: tall {AMBER};
        color: {AMBER};
    }}
    Button.warn:hover {{
        background: {AMBER};
        color: {BG};
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold {CYBER_CYAN}]╔  CONTROLS  ══════════════════════╗[/]\n",
            id="ctrl-header",
        )
        yield Button("▶  RESUME LOOP",  id="btn-resume",   classes="active")
        yield Button("⏸  PAUSE LOOP",   id="btn-pause",    classes="warn")
        yield Button("⚡  PING DAEMON",  id="btn-ping",     classes="")
        yield Button("⊘  GET PHASE",    id="btn-phase",    classes="")
        yield Button("⛔  SHUTDOWN",    id="btn-shutdown", classes="danger")
        yield Static(
            f"\n[{TEXT_DIM}]── Last Response ──────────────────[/]",
            id="ctrl-sep",
        )
        yield Label("—", id="ctrl-last-resp")
        yield Static(
            f"\n[{TEXT_DIM}]── Key Bindings ───────────────────[/]",
            id="ctrl-bindings",
        )
        yield Static(
            f"  [{CYBER_CYAN}]Ctrl+P[/] [{TEXT_DIM}]Pause / Resume[/]\n"
            f"  [{CYBER_CYAN}]Ctrl+R[/] [{TEXT_DIM}]Force Refresh[/]\n"
            f"  [{CYBER_CYAN}]Ctrl+C[/] [{TEXT_DIM}]Quit[/]\n"
            f"  [{TEXT_DIM}]Type[/] [{CYBER_CYAN}]help[/] [{TEXT_DIM}]in command bar[/]",
            id="ctrl-keys",
        )

    def update_resp(self, resp: str) -> None:
        self.query_one("#ctrl-last-resp", Label).update(
            f"[{HEADER_GLOW}]{resp}[/]"
        )


# ── ThoughtStream ─────────────────────────────────────────────────────────────

class ThoughtStream(Widget):
    """
    Centre column — the live SSE log feed from the daemon.
    Phase-colourised, timestamped, scrolling.
    """

    DEFAULT_CSS = f"""
    ThoughtStream {{
        column-span: 6;
        background: {BG};
        border: solid {CYBER_CYAN};
        padding: 0 1;
    }}
    RichLog {{
        background: {BG};
        color: {TEXT_BRIGHT};
        scrollbar-color: {CYBER_CYAN};
        scrollbar-background: {BG};
        scrollbar-size: 1 1;
    }}
    """

    def compose(self) -> ComposeResult:
        log = RichLog(
            id="thoughtstream-log",
            highlight=False,
            markup=True,
            wrap=True,
            max_lines=MAX_LOG_LINES,
        )
        log.border_title = "  THOUGHTSTREAM  "
        yield log

    def write(self, msg: str) -> None:
        self.query_one("#thoughtstream-log", RichLog).write(msg)


# ── Command Bar ───────────────────────────────────────────────────────────────

class CommandBar(Widget):
    """
    Bottom row — stylised input strip with prefix label and inline hints.
    """

    DEFAULT_CSS = f"""
    CommandBar {{
        column-span: 12;
        height: 3;
        background: {BG};
        border-top: solid {CYBER_CYAN};
        layout: horizontal;
    }}
    #cmd-prefix {{
        width: auto;
        height: 3;
        padding: 0 1;
        content-align: left middle;
        color: {CYBER_CYAN};
    }}
    #cmd-input {{
        height: 3;
        background: {BG};
        color: {TEXT_BRIGHT};
        border: none;
    }}
    #cmd-input:focus {{
        border: none;
    }}
    #cmd-hint {{
        width: auto;
        height: 3;
        padding: 0 1;
        content-align: right middle;
        color: {TEXT_DIM};
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static(f"[bold {CYBER_CYAN}]  ⌬ [/]", id="cmd-prefix")
        yield Input(
            placeholder="pause  /  resume  /  inject <cmd>  /  help",
            id="cmd-input",
        )
        yield Static(
            f"[{TEXT_DIM}]Ctrl+P=pause/resume   Ctrl+C=quit  [/]",
            id="cmd-hint",
        )


# ── Main Application ──────────────────────────────────────────────────────────

class YantraShell(App):
    """
    YantraOS Mission Control TUI – Phase 3: Cyberpunk Dashboard.
    Layout: Header / [Telemetry | ThoughtStream | Controls] / CommandBar
    """

    TITLE = "YantraOS // Mission Control"

    CSS = f"""
    Screen {{
        background: {BG};
        layout: grid;
        grid-size: 12;
        grid-rows: 3 1fr 3;
    }}

    /* ── Header spans full width ── */
    YantraHeader {{
        column-span: 12;
    }}

    /* ── Footer command bar ── */
    CommandBar {{
        column-span: 12;
    }}
    """

    BINDINGS = [
        Binding("ctrl+c", "quit",          "Quit",          show=True),
        Binding("ctrl+r", "force_refresh", "Refresh",       show=True),
        Binding("ctrl+p", "toggle_pause",  "Pause/Resume",  show=True),
    ]

    # ── State flags (updated from worker threads via call_from_thread) ────────
    _is_paused:  bool = False
    _connected:  bool = False

    def compose(self) -> ComposeResult:
        yield YantraHeader()
        yield TelemetryPanel()
        yield ThoughtStream()
        yield ControlPanel()
        yield CommandBar()

    def on_mount(self) -> None:
        self._poll_telemetry()
        self._stream_logs()
        # dim the focused border so the Input looks clean
        self.query_one("#cmd-input", Input).focus()

    # ── Telemetry polling (thread) ─────────────────────────────────────────────

    @work(thread=True, exclusive=True, name="telemetry-poll")
    def _poll_telemetry(self) -> None:
        telem  = self.query_one(TelemetryPanel)
        header = self.query_one(YantraHeader)
        ts_log = self.query_one(ThoughtStream)

        while True:
            try:
                data = _uds_get("/telemetry")

                phase = str(data.get("phase", "UNKNOWN")).upper()
                if "." in phase:
                    phase = phase.split(".")[-1]
                iteration  = int(data.get("iteration", 0))
                vram_used  = float(data.get("vram_used_gb",  0.0))
                vram_tot   = float(data.get("vram_total_gb", 0.0))
                gpu_util   = float(data.get("gpu_util_pct",  0.0))
                cpu_pct    = float(data.get("cpu_pct",       0.0))
                disk_free  = float(data.get("disk_free_gb",  0.0))
                model      = str(data.get("active_model",       "—"))
                routing    = str(data.get("inference_routing", "LOCAL"))

                def _apply(
                    p=phase, i=iteration, vu=vram_used, vt=vram_tot,
                    gu=gpu_util, cp=cpu_pct, df=disk_free,
                    m=model, r=routing,
                ) -> None:
                    telem.phase     = p
                    telem.iteration = i
                    telem.vram_used = vu
                    telem.vram_tot  = vt
                    telem.gpu_util  = gu
                    telem.cpu_pct   = cp
                    telem.disk_free = df
                    telem.model     = m
                    telem.routing   = r
                    telem.connected = True
                    telem.is_paused = self._is_paused
                    header.connected  = True
                    header.paused     = self._is_paused
                    header.iteration  = i

                self.app.call_from_thread(_apply)
                self._connected = True

            except (ConnectionRefusedError, FileNotFoundError, OSError):
                self._connected = False

                def _offline() -> None:
                    telem.connected  = False
                    telem.phase      = "OFFLINE"
                    header.connected = False
                    ts_log.write(
                        f"[{AMBER}][{time.strftime('%H:%M:%S')}]  ○  AWAITING DAEMON…  {UDS_PATH}[/]"
                    )

                self.app.call_from_thread(_offline)
                time.sleep(RECONNECT_DELAY)
                continue

            except Exception as exc:  # noqa: BLE001
                self.app.call_from_thread(
                    ts_log.write,
                    f"[{AMBER}][{time.strftime('%H:%M:%S')}]  ⚠  Telemetry error: {exc}[/]",
                )

            time.sleep(POLL_INTERVAL)

    # ── SSE ThoughtStream (thread) ─────────────────────────────────────────────

    @work(thread=True, exclusive=True, name="stream-logs")
    def _stream_logs(self) -> None:
        ts_log = self.query_one(ThoughtStream)

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

                    # Skip HTTP response headers
                    buf = b""
                    while b"\r\n\r\n" not in buf:
                        chunk = sock.recv(256)
                        if not chunk:
                            break
                        buf += chunk
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
                            if not line.startswith("data:"):
                                continue
                            json_part = line[5:].strip()
                            if not json_part or json_part == ":keepalive":
                                continue
                            try:
                                evt = json.loads(json_part)
                                msg = evt.get("log", "")
                                if msg:
                                    ts  = time.strftime("%H:%M:%S")
                                    coloured = _colorize_log(msg)
                                    self.app.call_from_thread(
                                        ts_log.write,
                                        f"[{TEXT_DIM}]{ts}[/]  {coloured}",
                                    )
                            except json.JSONDecodeError:
                                pass

            except (ConnectionRefusedError, FileNotFoundError, OSError):
                time.sleep(RECONNECT_DELAY)
                continue
            except Exception:  # noqa: BLE001
                time.sleep(RECONNECT_DELAY)
                continue

    # ── IPC dispatcher (thread) ────────────────────────────────────────────────

    @work(thread=True, name="ipc-post")
    def _ipc_send(self, body: dict) -> None:
        ts_log  = self.query_one(ThoughtStream)
        ctrl    = self.query_one(ControlPanel)
        ts      = time.strftime("%H:%M:%S")
        try:
            resp = _uds_post("/command", body)
            resp_str = json.dumps(resp)

            # Mirror pause state locally
            action = body.get("action", "")
            if action == "pause":
                self._is_paused = True
                self.app.call_from_thread(self._sync_pause_state)
            elif action == "resume":
                self._is_paused = False
                self.app.call_from_thread(self._sync_pause_state)

            self.app.call_from_thread(
                ts_log.write,
                f"[{TEXT_DIM}]{ts}[/]  [{HEADER_GLOW}]◀  IPC ▸ {resp_str}[/]",
            )
            self.app.call_from_thread(ctrl.update_resp, resp_str)

        except (ConnectionRefusedError, FileNotFoundError, OSError):
            self.app.call_from_thread(
                ts_log.write,
                f"[{TEXT_DIM}]{ts}[/]  [{AMBER}]⚠  Daemon not reachable — command dropped.[/]",
            )
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                ts_log.write,
                f"[{TEXT_DIM}]{ts}[/]  [{CRIMSON}]✖  Command failed: {exc}[/]",
            )

    def _sync_pause_state(self) -> None:
        """Update TelemetryPanel + YantraHeader reactive attrs from main thread."""
        telem  = self.query_one(TelemetryPanel)
        header = self.query_one(YantraHeader)
        ctrl   = self.query_one(ControlPanel)
        telem.is_paused   = self._is_paused
        header.paused     = self._is_paused

    # ── Button events ──────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-resume")
    def _btn_resume(self) -> None:
        self._ipc_send({"action": "resume"})

    @on(Button.Pressed, "#btn-pause")
    def _btn_pause(self) -> None:
        self._ipc_send({"action": "pause"})

    @on(Button.Pressed, "#btn-ping")
    def _btn_ping(self) -> None:
        self._ipc_send({"action": "ping"})

    @on(Button.Pressed, "#btn-phase")
    def _btn_phase(self) -> None:
        self._ipc_send({"action": "get_phase"})

    @on(Button.Pressed, "#btn-shutdown")
    def _btn_shutdown(self) -> None:
        self._ipc_send({"action": "shutdown"})

    # ── Input submission ───────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.clear()
        if not raw:
            return
        ts_log = self.query_one(ThoughtStream)
        ts_log.write(
            f"[{TEXT_DIM}]{time.strftime('%H:%M:%S')}[/]  "
            f"[{CYBER_CYAN}]⌬  CMD:[/]  [{TEXT_BRIGHT}]{raw}[/]"
        )
        self._handle_command(raw)

    @work(thread=True, name="cmd-parse")
    def _handle_command(self, raw: str) -> None:
        ts_log = self.query_one(ThoughtStream)
        lower  = raw.lower().strip()

        # ── Local commands ──────────────────────────────────────────
        if lower == "help":
            self.app.call_from_thread(
                ts_log.write,
                f"[{CYBER_CYAN}]┌─ AVAILABLE COMMANDS ──────────────────────────[/]\n"
                f"[{CYBER_CYAN}]│[/]  [{TEXT_BRIGHT}]pause[/]              Pause Kriya Loop\n"
                f"[{CYBER_CYAN}]│[/]  [{TEXT_BRIGHT}]resume[/]             Resume Kriya Loop\n"
                f"[{CYBER_CYAN}]│[/]  [{TEXT_BRIGHT}]inject <cmd>[/]       Inject command into REASON\n"
                f"[{CYBER_CYAN}]│[/]  [{TEXT_BRIGHT}]ping[/]               Roundtrip latency check\n"
                f"[{CYBER_CYAN}]│[/]  [{TEXT_BRIGHT}]get_phase[/]          Show current phase\n"
                f"[{CYBER_CYAN}]│[/]  [{TEXT_BRIGHT}]shutdown[/]           Request daemon shutdown\n"
                f"[{CYBER_CYAN}]└───────────────────────────────────────────────[/]",
            )
            return

        # ── IPC-routed commands ─────────────────────────────────────
        if lower in ("pause", "resume", "ping", "get_phase", "shutdown"):
            self.app.call_from_thread(self._ipc_send, {"action": lower})
            return

        if lower.startswith("inject "):
            inject_payload = raw[len("inject "):].strip()
            if not inject_payload:
                self.app.call_from_thread(
                    ts_log.write,
                    f"[{AMBER}]⚠  Usage: inject <command>[/]",
                )
                return
            self.app.call_from_thread(
                self._ipc_send,
                {"action": "inject", "payload": inject_payload},
            )
            return

        # ── Unknown ─────────────────────────────────────────────────
        self.app.call_from_thread(
            ts_log.write,
            f"[{AMBER}]⚠  Unknown: '[{TEXT_BRIGHT}]{raw}[/]'. "
            f"Type [{CYBER_CYAN}]help[/][{AMBER}].[/]",
        )

    # ── Keyboard actions ───────────────────────────────────────────────────────

    async def action_quit(self) -> None:
        self.exit()

    async def action_force_refresh(self) -> None:
        self._poll_telemetry()

    async def action_toggle_pause(self) -> None:
        if self._is_paused:
            self._ipc_send({"action": "resume"})
        else:
            self._ipc_send({"action": "pause"})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    YantraShell().run()
