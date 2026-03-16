"""
YantraOS — Mission Control TUI Shell  (core/tui_shell.py)
v1.3: "Connected Overseer" — Wi-Fi Manager Edition

Three Pillars
  1. Interface Split  — ThoughtStream (machine) | ChatPane (human)
  2. Keyboard Only   — Tab / Shift+Tab / Escape / Ctrl-*
  3. Dynamic Model   — Select dropdowns → IPC set_model dispatch

v1.2 Polish
  • Docked footer status strip (model + route + hot-keys at a glance)
  • Startup boot banner in ThoughtStream on mount
  • Phase-reactive ThoughtStream border colour
  • Richer LeftPane: box-drawing section headers, pill-badge model display
  • Message bubbles in ChatPane (framed user vs system messages)
  • Animated connection-pulse in header (blinking dots when offline)
  • Disk / VRAM / CPU colour thresholds with high-contrast danger marks
  • Iteration number flashes HEADER_GLOW colour when a new iteration starts
"""

from __future__ import annotations

import json
import re
import socket
import asyncio
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from textual import work, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Container
from textual.reactive import reactive
from textual.widget import Widget
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    RichLog,
    Select,
    Static,
)
from rich.text import Text

# ── Palette ───────────────────────────────────────────────────────────────────
BG           = "#080C14"
BG_MID       = "#0C1220"
BG_PANEL     = "#0F172A"
CYBER_CYAN   = "#00E5FF"
NEON_CYAN    = "#00FFFF"
ACID_GREEN   = "#39FF14"
AMBER        = "#FFB000"
CRIMSON      = "#FF2D55"
MAGENTA      = "#FF00FF"
TEXT_BRIGHT  = "#E8EAF6"
TEXT_MID     = "#94A3B8"
TEXT_DIM     = "#888888"
HEADER_GLOW  = "#1DE9B6"
BORDER_DIM   = "#1E3050"
BORDER_FOCUS = "#00E5FF"
PHASE_SENSE  = "#00E5FF"
PHASE_REASON = "#BF5AF2"
PHASE_ACT    = "#39FF14"
PHASE_REM    = "#FFB000"
PHASE_PATCH  = "#FF6B35"
PHASE_UPDATE = "#1DE9B6"
PHASE_OTHER  = "#4A5568"

# ── IPC ───────────────────────────────────────────────────────────────────────
UDS_PATH        = "/run/yantra/ipc.sock"
POLL_INTERVAL   = 2.0
RECONNECT_DELAY = 3.0
MAX_LOG_LINES   = 1000

# ── Model registry ────────────────────────────────────────────────────────────
CLOUD_MODELS: list[tuple[str, str]] = [
    ("Gemini 3.1 Pro",   "gemini-3.1-pro"),
    ("Gemini 2.5 Flash", "gemini-2.5-flash"),
    ("Gemini 2.5 Pro",   "gemini-2.5-pro"),
]
LOCAL_MODELS: list[tuple[str, str]] = [
    ("Llama 3",       "llama3"),
    ("Mistral",       "mistral"),
    ("DeepSeek R1",   "deepseek-r1"),
]

# ── Boot banner ───────────────────────────────────────────────────────────────
BOOT_BANNER = f"""\
[{CYBER_CYAN} bold]╔══════════════════════════════════════════════════════════╗[/]
[{CYBER_CYAN} bold]║[/]  [{HEADER_GLOW} bold]██╗   ██╗ █████╗ ███╗   ██╗████████╗██████╗  █████╗[/]  [{CYBER_CYAN} bold]║[/]
[{CYBER_CYAN} bold]║[/]  [{HEADER_GLOW} bold]╚██╗ ██╔╝██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔══██╗[/] [{CYBER_CYAN} bold]║[/]
[{CYBER_CYAN} bold]║[/]  [{HEADER_GLOW} bold] ╚████╔╝ ███████║██╔██╗ ██║   ██║   ██████╔╝███████║[/] [{CYBER_CYAN} bold]║[/]
[{CYBER_CYAN} bold]║[/]  [{HEADER_GLOW} bold]  ╚██╔╝  ██╔══██║██║╚██╗██║   ██║   ██╔══██╗██╔══██║[/] [{CYBER_CYAN} bold]║[/]
[{CYBER_CYAN} bold]║[/]  [{HEADER_GLOW} bold]   ██║   ██║  ██║██║ ╚████║   ██║   ██║  ██║██║  ██║[/] [{CYBER_CYAN} bold]║[/]
[{CYBER_CYAN} bold]║[/]  [{HEADER_GLOW} bold]   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝[/] [{CYBER_CYAN} bold]║[/]
[{CYBER_CYAN} bold]║[/]  [{TEXT_MID}]     Autonomous OS  //  Kriya Loop Engine  v1.2     [/] [{CYBER_CYAN} bold]║[/]
[{CYBER_CYAN} bold]╚══════════════════════════════════════════════════════════╝[/]
[{TEXT_DIM}]  Connecting to daemon at {UDS_PATH} …[/]\
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _uds_get(path: str, timeout: float = 5.0) -> dict[str, Any]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(UDS_PATH), timeout=timeout
        )
        writer.write(
            f"GET {path} HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode()
        )
        await writer.drain()
        raw = await reader.read()
        writer.close()
        await writer.wait_closed()
        _, _, body = raw.partition(b"\r\n\r\n")
        return json.loads(body.decode())
    except Exception:
        raise
        
async def _uds_post(path: str, body: dict, timeout: float = 5.0) -> dict[str, Any]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(UDS_PATH), timeout=timeout
        )
        payload = json.dumps(body).encode()
        headers = (
            f"POST {path} HTTP/1.0\r\n"
            "Host: localhost\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        writer.write(headers + payload)
        await writer.drain()
        raw = await reader.read()
        writer.close()
        await writer.wait_closed()
        _, _, resp_body = raw.partition(b"\r\n\r\n")
        return json.loads(resp_body.decode())
    except Exception:
        raise


def _gauge(pct: float, width: int = 16) -> str:
    """High-contrast ASCII gauge with threshold-aware colour."""
    pct    = max(0.0, min(100.0, pct))
    filled = int(pct / 100 * width)
    empty  = width - filled
    if pct < 60:
        color  = ACID_GREEN
        sym    = "█"
    elif pct < 85:
        color  = AMBER
        sym    = "█"
    else:
        color  = CRIMSON
        sym    = "█"
    bar = f"[{color}]{sym * filled}[/][{TEXT_DIM}]░{'░' * (empty - 1) if empty > 0 else ''}[/]"
    return f"[{BORDER_DIM}]▕[/]{bar}[{BORDER_DIM}]▏[/]"


def _pct_label(pct: float) -> str:
    col = CRIMSON if pct >= 85 else (AMBER if pct >= 60 else ACID_GREEN)
    return f"[{col} bold]{pct:5.1f}%[/]"


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
    u = msg.upper()
    if   "[SENSE]"    in u or "TELEMETRY"  in u: col = PHASE_SENSE
    elif "[REASON]"   in u or "REASONING"  in u: col = PHASE_REASON
    elif "[ACT]"      in u or "ACTION"     in u: col = PHASE_ACT
    elif "[REMEMBER]" in u or "MEMORY"     in u: col = PHASE_REM
    elif "[PATCH]"    in u or "CLOUD"      in u: col = PHASE_PATCH
    elif "[UPDATE]"   in u                      : col = PHASE_UPDATE
    elif "INJECT"     in u                      : col = HEADER_GLOW
    elif "THINKING"   in u                      : col = PHASE_REASON
    elif "STDOUT"     in u                      : col = ACID_GREEN
    elif "STDERR"     in u                      : col = CRIMSON
    elif "ERROR"      in u or "FAIL"       in u : col = CRIMSON
    elif "WARN"       in u                      : col = AMBER
    elif "PAUSED"     in u                      : col = AMBER
    elif "RESUMED"    in u                      : col = ACID_GREEN
    elif "SYSTEM"     in u or "DAEMON"     in u : col = TEXT_BRIGHT
    elif "ITERATION"  in u                      : col = NEON_CYAN
    else                                        : col = TEXT_MID
    return f"[{col}]{msg}[/]"


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _sec(title: str, width: int = 22) -> str:
    """Box-drawing section header for LeftPane."""
    pad = width - len(title) - 4
    return (
        f"[{BORDER_DIM}]╠══[/][{CYBER_CYAN} bold] {title} [/]"
        f"[{BORDER_DIM}]{'═' * max(0, pad)}╣[/]"
    )


# ── Header ────────────────────────────────────────────────────────────────────

class YantraHeader(Static):
    """Animated mission-control title bar with phase-reactive status."""

    connected: reactive[bool]  = reactive(False)
    paused:    reactive[bool]  = reactive(False)
    uptime:    reactive[float] = reactive(0.0)
    iteration: reactive[int]   = reactive(0)
    phase:     reactive[str]   = reactive("INIT")
    _flash:    reactive[bool]  = reactive(False)
    _pulse:    int             = 0

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
        self.set_interval(0.5, self._tick)

    def _tick(self) -> None:
        self.uptime = time.monotonic() - self._birth
        self._pulse = (self._pulse + 1) % 4
        self._flash = False  # reset flash
        self.refresh()

    def flash_iteration(self) -> None:
        """Call when a new iteration starts to momentarily glow the counter."""
        self._flash = True

    def render(self) -> Text:  # type: ignore[override]
        phase_col = _phase_color(self.phase)
        dot_chars = ["⠋", "⠙", "⠹", "⠸"] if not self.connected else ["●", "●", "●", "●"]
        dot       = dot_chars[self._pulse]
        dot_c     = ACID_GREEN if self.connected else AMBER

        hrs  = int(self.uptime // 3600)
        mins = int((self.uptime % 3600) // 60)
        secs = int(self.uptime % 60)
        up   = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        iter_col  = HEADER_GLOW if self._flash else TEXT_BRIGHT
        phase_str = self.phase.split(".")[-1] if "." in self.phase else self.phase

        t = Text(justify="center")
        t.append("◈ ", style=f"{CYBER_CYAN} bold")
        t.append("YANTRA", style=f"{CYBER_CYAN} bold")
        t.append("OS", style=f"{HEADER_GLOW} bold")
        t.append("  •  ", style=f"{TEXT_DIM}")
        t.append(f"KRIYA LOOP", style=f"{TEXT_BRIGHT} bold")
        t.append("  •  ", style=f"{TEXT_DIM}")

        if not self.connected:
            if self._pulse % 2 == 0:
                t.append("[ DAEMON OFFLINE - RECONNECTING ]", style=f"{CRIMSON} bold")
            else:
                t.append("[ DAEMON OFFLINE - RECONNECTING ]", style="bold")
        else:
            state     = "PAUSED" if self.paused else ("LIVE" if self.connected else "AWAIT")
            s_col     = AMBER if self.paused else (ACID_GREEN if self.connected else AMBER)
            t.append(dot, style=f"{dot_c} bold")
            t.append(f" {state}", style=f"{s_col} bold")

        t.append("  │  ", style=f"{TEXT_DIM}")
        t.append("PHASE:", style=f"{TEXT_DIM}")
        t.append(f" {phase_str}", style=f"{phase_col} bold")
        t.append("  │  ", style=f"{TEXT_DIM}")
        t.append("ITER ", style=f"{TEXT_DIM}")
        t.append(f"#{self.iteration:,}", style=f"{iter_col} bold")
        t.append(f"  │  up {up}", style=f"{TEXT_DIM}")
        return t


# ── Left Pane ─────────────────────────────────────────────────────────────────

class LeftPane(Widget):
    """
    Operator control panel — telemetry metrics, model/route selectors,
    action buttons, and keyboard shortcut legend.
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
    LeftPane {{
        width: 100%;
        height: 100%;
        background: {BG_PANEL};
        border-right: solid {CYBER_CYAN};
        padding: 0 1;
        color: {TEXT_BRIGHT};
    }}
    LeftPane #telem-block {{
        height: auto;
    }}
    LeftPane .section-sep {{
        height: 1;
        color: {BORDER_DIM};
    }}
    LeftPane #route-lbl {{
        height: 1;
        padding: 0 0;
        color: {CYBER_CYAN};
        text-style: bold;
    }}
    LeftPane #model-lbl {{
        height: 1;
        padding: 0 0;
        color: {CYBER_CYAN};
        text-style: bold;
    }}
    LeftPane Select {{
        width: 100%;
        background: {BG};
        color: {TEXT_BRIGHT};
        border: solid {BORDER_DIM};
        margin-bottom: 1;
        height: 3;
    }}
    LeftPane Select:focus {{
        border: solid {CYBER_CYAN};
    }}
    LeftPane SelectOverlay {{
        background: {BG_PANEL};
        border: solid {CYBER_CYAN};
        color: {TEXT_BRIGHT};
    }}
    LeftPane #resp-lbl {{
        height: 1;
        color: {TEXT_DIM};
        text-style: bold;
    }}
    LeftPane #resp-val {{
        height: 1;
        color: {HEADER_GLOW};
    }}
    LeftPane Button {{
        width: 100%;
        height: 2;
        margin-bottom: 1;
        background: {BG};
        color: {CYBER_CYAN};
        border: solid {BORDER_DIM};
    }}
    LeftPane Button:focus {{
        border: solid {CYBER_CYAN};
        background: {BG_MID};
    }}
    LeftPane Button.warn {{
        border: solid {AMBER};
        color: {AMBER};
    }}
    LeftPane Button.warn:focus {{
        background: {BG_MID};
        border: solid {AMBER};
    }}
    LeftPane Button.danger {{
        border: solid {CRIMSON};
        color: {CRIMSON};
    }}
    LeftPane Button.danger:focus {{
        background: {BG_MID};
        border: solid {CRIMSON};
    }}
    LeftPane Button.active {{
        border: solid {ACID_GREEN};
        color: {ACID_GREEN};
    }}
    LeftPane Button.active:focus {{
        background: {BG_MID};
        border: solid {ACID_GREEN};
    }}
    LeftPane #keys-block {{
        height: auto;
        color: {TEXT_DIM};
        padding-top: 1;
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static(id="telem-block")
        yield Static(id="sep-route", classes="section-sep")
        yield Static(f"  ROUTE", id="route-lbl")
        yield Select(
            [("  Cloud ☁", "Cloud"), ("  Local ⬡", "Local")],
            id="route-select",
            value="Local",
            allow_blank=False,
        )
        yield Static(f"  MODEL", id="model-lbl")
        yield Select(
            [(f"  {n}", v) for n, v in LOCAL_MODELS],
            id="model-select",
            value=LOCAL_MODELS[0][1],
            allow_blank=False,
        )
        yield Static(id="sep-ctrl", classes="section-sep")
        yield Button("▶  RESUME LOOP",   id="btn-resume",   classes="active")
        yield Button("⏸  PAUSE LOOP",    id="btn-pause",    classes="warn")
        yield Button("⚡  PING DAEMON",  id="btn-ping")
        yield Button("⛔  SHUTDOWN",     id="btn-shutdown", classes="danger")
        yield Static(id="sep-resp", classes="section-sep")
        yield Static("  LAST RESPONSE", id="resp-lbl")
        yield Label("  —", id="resp-val")
        yield Static(
            f"\n"
            f"[{TEXT_DIM}]  ─── KEY BINDINGS ───────────[/]\n"
            f"[{CYBER_CYAN}]  Tab[/][{TEXT_DIM}]      cycle panels[/]\n"
            f"[{CYBER_CYAN}]  Shift+Tab[/][{TEXT_DIM}] reverse cycle[/]\n"
            f"[{CYBER_CYAN}]  Escape[/][{TEXT_DIM}]   → command input[/]\n"
            f"[{CYBER_CYAN}]  Ctrl+P[/][{TEXT_DIM}]   pause / resume[/]\n"
            f"[{CYBER_CYAN}]  Ctrl+R[/][{TEXT_DIM}]   force refresh[/]\n"
            f"[{CYBER_CYAN}]  Ctrl+C[/][{TEXT_DIM}]   quit[/]",
            id="keys-block",
        )

    def on_mount(self) -> None:
        for widget in self.query("Select, Button"):
            widget.can_focus = True

    # ── Telemetry render ──────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        vram_pct  = (self.vram_used / self.vram_tot * 100) if self.vram_tot > 0 else 0.0
        disk_used = max(0, (100 - min(self.disk_free * 5, 100)))
        disk_pct  = disk_used

        vbar  = _gauge(vram_pct)
        gbar  = _gauge(self.gpu_util)
        cbar  = _gauge(self.cpu_pct)
        dbar  = _gauge(disk_pct)

        vram_col   = CRIMSON if vram_pct  >= 85 else (AMBER if vram_pct  >= 60 else ACID_GREEN)
        disk_col   = CRIMSON if self.disk_free < 3 else (AMBER if self.disk_free < 10 else ACID_GREEN)
        phase_col  = _phase_color(self.phase)

        if self.is_paused and self.connected:
            status_icon = f"[{AMBER} bold]⏸  PAUSED[/]"
        elif self.connected:
            status_icon = f"[{ACID_GREEN} bold]▶  LIVE[/]"
        else:
            status_icon = f"[{AMBER} bold]○  AWAIT…[/]"

        conn_dot  = f"[{ACID_GREEN}]●[/]" if self.connected else f"[{AMBER}]◌[/]"
        phase_str = (self.phase.split(".")[-1] if "." in self.phase else self.phase)[:12]

        # Section header arts
        top_bar   = f"[{CYBER_CYAN} bold]╔══  YANTRA  ══════════════╗[/]"
        bot_bar   = f"[{CYBER_CYAN} bold]╚══════════════════════════╝[/]"
        sep_line  = f"[{BORDER_DIM}]  ──────────────────────────[/]"

        block = self.query_one("#telem-block", Static)
        block.update(
            f"{top_bar}\n"
            f"  {conn_dot}  {status_icon}\n"
            f"[{TEXT_DIM}]  Phase  [/][{phase_col} bold]{phase_str}[/]\n"
            f"[{TEXT_DIM}]  Iter   [/][{NEON_CYAN} bold]#{self.iteration:,}[/]\n"
            f"{sep_line}\n"
            f"[{TEXT_DIM}]  VRAM[/]  [{vram_col}]{self.vram_used:.1f}[/][{TEXT_DIM}]/{self.vram_tot:.0f} GB[/]  "
            f"{_pct_label(vram_pct)}\n"
            f"         {vbar}\n"
            f"[{TEXT_DIM}]  GPU [/]  {_pct_label(self.gpu_util)}\n"
            f"         {gbar}\n"
            f"[{TEXT_DIM}]  CPU [/]  {_pct_label(self.cpu_pct)}\n"
            f"         {cbar}\n"
            f"[{TEXT_DIM}]  DISK[/]  [{disk_col}]{self.disk_free:.1f} GB free[/]\n"
            f"         {dbar}\n"
            f"[{TEXT_DIM}]  MODEL[/] [{HEADER_GLOW}]{self.model[:16]}[/]\n"
            f"[{TEXT_DIM}]  ROUTE[/] [{CYBER_CYAN}]{self.routing}[/]\n"
            f"{bot_bar}"
        )

        # Section dividers
        try:
            self.query_one("#sep-route", Static).update(
                f"\n[{BORDER_DIM}]  ─── AI ENGINE ──────────────[/]"
            )
            self.query_one("#sep-ctrl", Static).update(
                f"\n[{BORDER_DIM}]  ─── CONTROLS ───────────────[/]"
            )
            self.query_one("#sep-resp", Static).update(
                f"\n[{BORDER_DIM}]  ─── IPC STATUS ─────────────[/]"
            )
        except Exception:
            pass

    # ── Reactive watchers ─────────────────────────────────────────────────────

    def watch_phase(self, _: Any)      -> None: self._rebuild()
    def watch_iteration(self, _: Any)  -> None: self._rebuild()
    def watch_vram_used(self, _: Any)  -> None: self._rebuild()
    def watch_vram_tot(self, _: Any)   -> None: self._rebuild()
    def watch_gpu_util(self, _: Any)   -> None: self._rebuild()
    def watch_cpu_pct(self, _: Any)    -> None: self._rebuild()
    def watch_disk_free(self, _: Any)  -> None: self._rebuild()
    def watch_model(self, _: Any)      -> None: self._rebuild()
    def watch_routing(self, _: Any)    -> None: self._rebuild()
    def watch_connected(self, _: Any)  -> None: self._rebuild()
    def watch_is_paused(self, _: Any)  -> None: self._rebuild()

    def update_resp(self, resp: str) -> None:
        short = resp[:24] + ("…" if len(resp) > 24 else "")
        self.query_one("#resp-val", Label).update(f"  [{HEADER_GLOW}]{short}[/]")


# ── ThoughtStream ─────────────────────────────────────────────────────────────

class ThoughtStream(Widget):
    """
    Top-right panel — read-only Kriya Loop machine output.
    Border colour tracks the current cognitive phase.
    """

    _phase_col: reactive[str] = reactive(CYBER_CYAN)

    DEFAULT_CSS = f"""
    ThoughtStream {{
        background: {BG};
        border: solid {CYBER_CYAN};
        border-title-color: {CYBER_CYAN};
        border-title-align: left;
        border-title-style: bold;
        padding: 0 1;
    }}
    ThoughtStream RichLog {{
        background: {BG};
        color: {TEXT_BRIGHT};
        scrollbar-color: {CYBER_CYAN};
        scrollbar-background: {BG};
        scrollbar-size: 1 1;
    }}
    """

    def compose(self) -> ComposeResult:
        log = RichLog(
            id="ts-log",
            highlight=False,
            markup=True,
            wrap=True,
            max_lines=MAX_LOG_LINES,
            auto_scroll=True,
        )
        yield log

    def on_mount(self) -> None:
        self.border_title = "  ⚙  KRIYA THOUGHTSTREAM  "
        self.border_subtitle = "  read-only · machine output  "

    def set_phase(self, phase: str) -> None:
        col = _phase_color(phase)
        self.styles.border = ("heavy", col)
        self._phase_col = col

    def write(self, msg: str) -> None:
        self.query_one("#ts-log", RichLog).write(msg)


# ── Chat Pane ─────────────────────────────────────────────────────────────────

class ChatPane(Widget):
    """
    Bottom-right panel — human operator interface.
    Isolated from ThoughtStream so machine churn never obscures user commands.
    """

    DEFAULT_CSS = f"""
    ChatPane {{
        background: {BG_PANEL};
        border: solid {CYBER_CYAN};
        border-title-color: {HEADER_GLOW};
        border-title-align: left;
        border-title-style: bold;
        layout: vertical;
    }}
    ChatPane:focus-within {{
        border: solid {HEADER_GLOW};
    }}
    ChatPane #chat-log {{
        background: {BG_PANEL};
        color: {TEXT_BRIGHT};
        scrollbar-color: {HEADER_GLOW};
        scrollbar-background: {BG_PANEL};
        scrollbar-size: 1 1;
    }}
    ChatPane #input-strip {{
        height: 3;
        background: {BG};
        border-top: solid {BORDER_DIM};
        layout: horizontal;
    }}
    ChatPane #chat-prefix {{
        width: 6;
        height: 3;
        content-align: left middle;
        color: {CYBER_CYAN};
        text-style: bold;
    }}
    ChatPane #chat-input {{
        height: 3;
        background: {BG};
        color: {TEXT_BRIGHT};
        border: none;
    }}
    ChatPane #chat-input:focus {{
        border: none;
    }}
    """

    def compose(self) -> ComposeResult:
        yield RichLog(
            id="chat-log",
            highlight=False,
            markup=True,
            wrap=True,
            max_lines=500,
            auto_scroll=True,
        )
        with Container(id="input-strip"):
            yield Static(f" [{CYBER_CYAN} bold]⌬ ▶[/] ", id="chat-prefix")
            yield Input(
                placeholder="help  ·  pause  ·  resume  ·  install_os  ·  inject <cmd>",
                id="chat-input",
            )

    def on_mount(self) -> None:
        self.border_title  = "  💬  COMMAND INTERFACE  "
        self.border_subtitle = "  your messages stay here  "
        self.query_one("#chat-input", Input).can_focus = True

    def _log(self) -> RichLog:
        return self.query_one("#chat-log", RichLog)

    def write_user(self, msg: str) -> None:
        """Styled user message bubble."""
        ts = _ts()
        self._log().write(
            f"[{TEXT_DIM}]{ts}[/]  [{CYBER_CYAN} bold]╭─ YOU ───────────────────────────────────╮[/]"
        )
        self._log().write(
            f"         [{CYBER_CYAN}]│[/] [{TEXT_BRIGHT}]{msg}[/]"
        )
        self._log().write(
            f"         [{CYBER_CYAN} bold]╰─────────────────────────────────────────╯[/]"
        )

    def write_system(self, msg: str) -> None:
        """System / IPC response line."""
        ts = _ts()
        self._log().write(
            f"[{TEXT_DIM}]{ts}[/]  [{HEADER_GLOW}]◀ SYS ▸[/]  {msg}"
        )

    def write_info(self, msg: str) -> None:
        """Informational / help content."""
        self._log().write(msg)

    def get_input(self) -> Input:
        return self.query_one("#chat-input", Input)


# ── Footer Strip ──────────────────────────────────────────────────────────────

class StatusFooter(Static):
    """
    Docked bottom strip — shows active model, route, and hot-key glyphs.
    Updated whenever model/route changes.
    """

    model:  reactive[str] = reactive("llama3")
    route:  reactive[str] = reactive("Local")
    status: reactive[str] = reactive("AWAIT")

    DEFAULT_CSS = f"""
    StatusFooter {{
        dock: bottom;
        height: 1;
        background: {BG_MID};
        border-top: solid {BORDER_DIM};
        color: {TEXT_DIM};
        content-align: left middle;
        padding: 0 2;
    }}
    """

    def render(self) -> Text:  # type: ignore[override]
        route_col = CYBER_CYAN   if self.route  == "Cloud" else ACID_GREEN
        stat_col  = ACID_GREEN   if self.status == "LIVE"  else (AMBER if self.status == "AWAIT" else AMBER)

        t = Text(overflow="ellipsis")
        t.append(" ⚙ ", style=f"{CYBER_CYAN}")
        t.append(f"{self.model}", style=f"{HEADER_GLOW} bold")
        t.append("  via  ", style=f"{TEXT_DIM}")
        t.append(f"{self.route}", style=f"{route_col} bold")
        t.append("    │    ", style=f"{TEXT_DIM}")
        t.append(f"● {self.status}", style=f"{stat_col}")
        t.append("    │    ", style=f"{TEXT_DIM}")
        t.append("Ctrl+N", style=f"{CYBER_CYAN}")
        t.append(" Wi-Fi  ", style=f"{TEXT_DIM}")
        t.append("Tab", style=f"{CYBER_CYAN}")
        t.append(" panels  ", style=f"{TEXT_DIM}")
        t.append("Esc", style=f"{CYBER_CYAN}")
        t.append(" → input  ", style=f"{TEXT_DIM}")
        t.append("Ctrl+P", style=f"{CYBER_CYAN}")
        t.append(" pause  ", style=f"{TEXT_DIM}")
        t.append("Ctrl+C", style=f"{CYBER_CYAN}")
        t.append(" quit", style=f"{TEXT_DIM}")
        return t


# ── Wi-Fi Network Manager ────────────────────────────────────────────────────

@dataclass
class WifiNetwork:
    """Parsed nmcli Wi-Fi network entry."""
    ssid:     str
    signal:   int   # 0-100
    security: str   # WPA2, WPA3, open, etc.
    in_use:   bool  = False

    @property
    def bars(self) -> str:
        """Convert signal 0-100 to a 4-bar visual glyph string."""
        if self.signal >= 80:
            glyphs = f"[{ACID_GREEN}]▂▄▆█[/]"
        elif self.signal >= 55:
            glyphs = f"[{ACID_GREEN}]▂▄▆[/][{TEXT_DIM}]█[/]"
        elif self.signal >= 30:
            glyphs = f"[{AMBER}]▂▄[/][{TEXT_DIM}]▆█[/]"
        else:
            glyphs = f"[{CRIMSON}]▂[/][{TEXT_DIM}]▄▆█[/]"
        return glyphs

    @property
    def security_badge(self) -> str:
        s = self.security.upper()
        if "WPA3" in s:
            return f"[{ACID_GREEN}]WPA3[/]"
        if "WPA2" in s or "WPA" in s:
            return f"[{CYBER_CYAN}]WPA2[/]"
        if "WEP" in s:
            return f"[{AMBER}]WEP [/]"
        return f"[{TEXT_DIM}]OPEN[/]"


def _scan_wifi() -> list[WifiNetwork]:
    """
    Run nmcli to scan for Wi-Fi networks and return parsed results.
    Uses -t (terse) -f (fields) output for reliable parsing.
    Called from a worker thread — never on the UI thread.
    """
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        raise RuntimeError("nmcli not found. Is NetworkManager installed?")
    except subprocess.TimeoutExpired:
        raise RuntimeError("nmcli scan timed out (15 s).")

    networks: list[WifiNetwork] = []
    seen: set[str] = set()

    for line in result.stdout.splitlines():
        # terse format: IN-USE:SSID:SIGNAL:SECURITY — colons are separators
        # SSID itself may contain backslash-escaped colons
        parts = re.split(r"(?<!\\):", line, maxsplit=3)
        if len(parts) < 4:
            continue
        in_use_raw, ssid_raw, signal_raw, security_raw = parts
        ssid = ssid_raw.replace("\\:", ":").strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        try:
            signal = int(signal_raw.strip())
        except ValueError:
            signal = 0
        networks.append(WifiNetwork(
            ssid     = ssid,
            signal   = signal,
            security = security_raw.strip() or "--",
            in_use   = in_use_raw.strip() == "*",
        ))

    # Sort: in-use first, then by descending signal
    networks.sort(key=lambda n: (not n.in_use, -n.signal))
    return networks


def _nmcli_connect(ssid: str, password: str) -> tuple[bool, str]:
    """
    Attempt to join a Wi-Fi network via nmcli.
    Returns (success, message). Called from a worker thread.
    """
    cmd: list[str]
    if password:
        cmd = ["nmcli", "device", "wifi", "connect", ssid, "password", password]
    else:
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = (res.stdout + res.stderr).strip()
        if res.returncode == 0 and "successfully activated" in output.lower():
            return True, f"Connected to '{ssid}'."
        return False, output or f"nmcli returned code {res.returncode}."
    except subprocess.TimeoutExpired:
        return False, "Connection timed out (30 s)."
    except Exception as exc:
        return False, str(exc)


@dataclass
class ActiveConnection:
    """Parsed nmcli active connection entry."""
    name: str
    conn_type: str  # ethernet, wifi, gsm, bluetooth, etc.
    state: str      # activated, activating, etc.

    @property
    def label(self) -> str:
        """Human-friendly label for the connection type."""
        t = self.conn_type.lower()
        if "ethernet" in t or "802-3" in t:
            return "Ethernet"
        if "gsm" in t or "cdma" in t or "bluetooth" in t:
            return "Tethering"
        if "wifi" in t or "802-11" in t:
            return "Wi-Fi"
        return self.conn_type.capitalize()

    @property
    def is_hardline(self) -> bool:
        """True if this is a non-Wi-Fi wired/tethered connection."""
        t = self.conn_type.lower()
        return any(k in t for k in ("ethernet", "802-3", "gsm", "cdma", "bluetooth"))


def _check_active_connections() -> list[ActiveConnection]:
    """
    Query nmcli for ALL active connections (not just Wi-Fi).
    Returns parsed list. Called from a worker thread.
    """
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE,STATE", "con", "show", "--active"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    connections: list[ActiveConnection] = []
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3:
            connections.append(ActiveConnection(
                name=parts[0].strip(),
                conn_type=parts[1].strip(),
                state=parts[2].strip(),
            ))
    return connections


class PasswordModal(ModalScreen[str | None]):
    """
    Floating modal — prompts for a Wi-Fi password.
    Returns the entered password string or None on cancel.
    """

    DEFAULT_CSS = f"""
    PasswordModal {{
        align: center middle;
    }}
    PasswordModal #pw-dialog {{
        width: 60;
        height: 14;
        background: {BG_PANEL};
        border: solid {CYBER_CYAN};
        border-title-color: {CYBER_CYAN};
        border-title-align: center;
        padding: 1 2;
        layout: vertical;
    }}
    PasswordModal #pw-ssid-label {{
        height: 2;
        content-align: center middle;
        color: {HEADER_GLOW};
        text-style: bold;
    }}
    PasswordModal #pw-hint {{
        height: 1;
        color: {TEXT_DIM};
        content-align: center middle;
    }}
    PasswordModal #pw-input {{
        height: 3;
        background: {BG};
        color: {TEXT_BRIGHT};
        border: solid {BORDER_DIM};
        margin-top: 1;
    }}
    PasswordModal #pw-input:focus {{
        border: solid {CYBER_CYAN};
    }}
    PasswordModal #pw-buttons {{
        height: 3;
        layout: horizontal;
        margin-top: 1;
    }}
    PasswordModal #pw-connect {{
        width: 1fr;
        background: {BG};
        color: {ACID_GREEN};
        border: solid {ACID_GREEN};
    }}
    PasswordModal #pw-connect:focus {{
        background: {BG_MID};
    }}
    PasswordModal #pw-cancel {{
        width: 1fr;
        background: {BG};
        color: {CRIMSON};
        border: solid {CRIMSON};
        margin-left: 1;
    }}
    PasswordModal #pw-cancel:focus {{
        background: {BG_MID};
    }}
    """

    def __init__(self, ssid: str) -> None:
        super().__init__()
        self._ssid = ssid

    def compose(self) -> ComposeResult:
        with Vertical(id="pw-dialog"):
            yield Static(
                f"[{CYBER_CYAN}]━━━  Wi-Fi Password  ━━━[/]\n"
                f"[{HEADER_GLOW} bold]{self._ssid}[/]",
                id="pw-ssid-label",
            )
            yield Label(
                f"[{TEXT_DIM}]Leave blank for open networks. Press Enter to connect.[/]",
                id="pw-hint",
            )
            yield Input(
                placeholder="Password …",
                password=True,
                id="pw-input",
            )
            with Horizontal(id="pw-buttons"):
                yield Button("▶  CONNECT", id="pw-connect", variant="default")
                yield Button("✕  CANCEL",  id="pw-cancel",  variant="default")

    def on_mount(self) -> None:
        # Focus password field immediately; ModalScreen has no widget border_title
        pw_input = self.query_one("#pw-input", Input)
        pw_input.can_focus = True
        for b in self.query("Button"):
            b.can_focus = True
        pw_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    @on(Button.Pressed, "#pw-connect")
    def _connect(self) -> None:
        pw = self.query_one("#pw-input", Input).value
        self.dismiss(pw)

    @on(Button.Pressed, "#pw-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    BINDINGS = [Binding("escape", "dismiss_cancel", show=False)]

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)


class NetworkModal(ModalScreen[None]):
    """
    Full-screen (centred) Wi-Fi network browser.
    Scan → pick SSID → enter password → connect — all inside the TUI.
    """

    DEFAULT_CSS = f"""
    NetworkModal {{
        align: center middle;
    }}
    NetworkModal #net-dialog {{
        width: 80;
        height: 30;
        background: {BG_PANEL};
        border: solid {CYBER_CYAN};
        border-title-color: {CYBER_CYAN};
        border-title-align: left;
        layout: vertical;
        padding: 0;
    }}
    NetworkModal #net-table-wrap {{
        height: 1fr;
        background: {BG};
        padding: 0 1;
    }}
    NetworkModal DataTable {{
        background: {BG};
        color: {TEXT_BRIGHT};
        scrollbar-color: {CYBER_CYAN};
        scrollbar-background: {BG};
        scrollbar-size: 1 1;
    }}
    NetworkModal DataTable > .datatable--header {{
        background: {BG_MID};
        color: {CYBER_CYAN};
        text-style: bold;
    }}
    NetworkModal DataTable > .datatable--cursor {{
        background: {CYBER_CYAN};
        color: {BG};
    }}
    NetworkModal #net-active-badge {{
        height: auto;
        max-height: 3;
        background: #0a2a0a;
        color: {ACID_GREEN};
        text-style: bold;
        content-align: left middle;
        padding: 0 2;
        border-bottom: solid {ACID_GREEN};
        display: none;
    }}
    NetworkModal #net-status {{
        height: 2;
        background: {BG_MID};
        border-top: solid {BORDER_DIM};
        color: {TEXT_DIM};
        content-align: left middle;
        padding: 0 2;
    }}
    NetworkModal #net-footer {{
        height: 3;
        background: {BG_MID};
        border-top: solid {BORDER_DIM};
        layout: horizontal;
        padding: 0 1;
    }}
    NetworkModal #btn-scan {{
        width: auto;
        background: {BG};
        color: {CYBER_CYAN};
        border: solid {CYBER_CYAN};
        margin-right: 1;
    }}
    NetworkModal #btn-scan:focus {{
        background: {BG_MID};
    }}
    NetworkModal #btn-close {{
        width: auto;
        background: {BG};
        color: {CRIMSON};
        border: solid {CRIMSON};
    }}
    NetworkModal #btn-close:focus {{
        background: {BG_MID};
    }}
    """

    BINDINGS = [
        Binding("escape",     "close_modal", "Close",  show=True),
        Binding("ctrl+r",     "do_scan",     "Rescan", show=True),
        Binding("tab",        "focus_next",  "",       show=False),
        Binding("shift+tab",  "focus_previous", "",    show=False),
    ]

    _networks: list[WifiNetwork]

    def __init__(self) -> None:
        super().__init__()
        self._networks = []  # instance-level; never shared between modal invocations
        self._suppress_scan = False
        self._has_hardline = False  # True if Ethernet/USB tethering is active

    def compose(self) -> ComposeResult:
        with Vertical(id="net-dialog"):
            yield Static(id="net-active-badge")
            with Container(id="net-table-wrap"):
                yield DataTable(id="net-table", cursor_type="row", show_cursor=True)
            yield Static(id="net-status")
            with Horizontal(id="net-footer"):
                yield Button("⟳  RESCAN",  id="btn-scan")
                yield Button("✕  CLOSE",   id="btn-close")

    def on_mount(self) -> None:
        self.border_title = "  📡  NETWORK MANAGER  "
        table = self.query_one("#net-table", DataTable)
        table.can_focus = True
        for b in self.query("Button"):
            b.can_focus = True
        table.add_columns("  ", "SSID", "SIGNAL", "STRENGTH", "SECURITY")
        self._set_status(f"[{AMBER}]Press Ctrl+R or ⟳ RESCAN to scan for networks.[/]")
        self._do_scan()

    def _set_status(self, msg: str) -> None:
        self.query_one("#net-status", Static).update(f"  {msg}")

    # ── Scan ─────────────────────────────────────────────────────────────────

    def action_do_scan(self) -> None:
        self._do_scan()

    @on(Button.Pressed, "#btn-scan")
    def _btn_scan(self) -> None:
        self._do_scan()

    @work(thread=True, name="wifi-scan")
    def _do_scan(self) -> None:
        self.app.call_from_thread(
            self._set_status,
            f"[{AMBER}]⟳  Scanning … (nmcli)[/]",
        )

        # ── Check for active Ethernet / USB tethering first ────────────
        active_conns = _check_active_connections()
        hardline = [c for c in active_conns if c.is_hardline]
        self._has_hardline = bool(hardline)
        if hardline:
            labels = ", ".join(f"{c.name} ({c.label})" for c in hardline)
            badge_text = f"  🌐 ACTIVE CONNECTION DETECTED: {labels}"
            self.app.call_from_thread(self._show_active_badge, badge_text)
        else:
            self.app.call_from_thread(self._hide_active_badge)

        try:
            nets = _scan_wifi()
        except Exception as exc:
            self.app.call_from_thread(
                self._set_status,
                f"[{CRIMSON}]✖  Scan failed: {exc}[/]",
            )
            return

        self._networks = nets
        self.app.call_from_thread(self._populate_table, nets)

    def _show_active_badge(self, text: str) -> None:
        """Show the green active-connection badge at the top of the modal."""
        badge = self.query_one("#net-active-badge", Static)
        badge.update(text)
        badge.styles.display = "block"

    def _hide_active_badge(self) -> None:
        """Hide the active-connection badge."""
        badge = self.query_one("#net-active-badge", Static)
        badge.styles.display = "none"

    def _populate_table(self, nets: list[WifiNetwork]) -> None:
        table = self.query_one("#net-table", DataTable)
        table.clear()
        if not nets:
            # Only show the alarming "No networks found" if there is no hardline
            if self._has_hardline:
                self._set_status(
                    f"[{TEXT_DIM}]No Wi-Fi networks found — "
                    f"[{ACID_GREEN} bold]hardline connection is active[/][{TEXT_DIM}].[/]"
                )
            else:
                self._set_status(f"[{AMBER}]No networks found. Try rescanning.[/]")
            return
        for net in nets:
            in_use_glyph = f"[{ACID_GREEN} bold]★[/]" if net.in_use else "  "
            table.add_row(
                in_use_glyph,
                f"[{TEXT_BRIGHT} bold]{net.ssid}[/]" if net.in_use else net.ssid,
                f"{net.signal:3d}%",
                net.bars,
                net.security_badge,
            )
        self._set_status(
            f"[{ACID_GREEN}]{len(nets)} network(s) found.[/]  "
            f"[{TEXT_DIM}]↑↓ navigate · Enter connect · Ctrl+R rescan · Esc close[/]"
        )
        table.focus()

    # ── Connect flow ─────────────────────────────────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """User pressed Enter on a network row — launch password modal."""
        idx = event.cursor_row
        if idx < 0 or idx >= len(self._networks):
            return
        net = self._networks[idx]
        needs_auth = net.security.upper() not in ("", "--", "OPEN")
        if needs_auth:
            # Capture SSID NOW — before modal opens and cursor can change
            captured_ssid = net.ssid
            self.app.push_screen(
                PasswordModal(captured_ssid),
                lambda pw, ssid=captured_ssid: self._on_password_received(pw, ssid),
            )
        else:
            # Open network — connect directly
            self._connect(net.ssid, "")

    def _on_password_received(self, password: str | None, ssid: str) -> None:
        """Callback after PasswordModal is dismissed with the pre-captured SSID."""
        if password is None:
            return  # User cancelled
        self._connect(ssid, password)

    @work(thread=True, name="wifi-connect")
    def _connect(self, ssid: str, password: str) -> None:
        self.app.call_from_thread(
            self._set_status,
            f"[{AMBER}]⟳  Connecting to '[{TEXT_BRIGHT}]{ssid}[/]' …[/]",
        )
        ok, msg = _nmcli_connect(ssid, password)
        if ok:
            self.app.call_from_thread(
                self._set_status,
                f"[{ACID_GREEN} bold]✔  {msg}[/]",
            )
            self.app.call_from_thread(
                self.app.notify,
                f"Connected to '{ssid}'.",
                title="Wi-Fi ✔",
                severity="information",
                timeout=5,
            )
            # Refresh table to show ★ on active network
            self.app.call_from_thread(self._do_scan)
        else:
            self.app.call_from_thread(
                self._set_status,
                f"[{CRIMSON}]✖  {msg}[/]",
            )
            self.app.call_from_thread(
                self.app.notify,
                f"Failed: {msg[:80]}",
                title="Wi-Fi ✖",
                severity="error",
                timeout=7,
            )

    @on(Button.Pressed, "#btn-close")
    def _btn_close(self) -> None:
        self.dismiss()

    def action_close_modal(self) -> None:
        self.dismiss()


# ── Main Application ──────────────────────────────────────────────────────────

class YantraShell(App):
    """
    YantraOS Mission Control TUI — v1.3 Connected Overseer.
    Ctrl+N opens the native Wi-Fi Network Manager overlay.
    """

    TITLE = "YantraOS // Mission Control"

    CSS = f"""
    Screen {{
        background: {BG};
        layout: vertical;
    }}

    YantraHeader {{
        dock: top;
        height: 3;
    }}

    StatusFooter {{
        dock: bottom;
        height: 1;
    }}

    #main-body {{
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr 2fr;
        grid-rows: 62% 38%;
        width: 100%;
        height: 100%;
    }}

    LeftPane {{
        row-span: 2;
        height: 100%;
    }}

    ThoughtStream {{
        column-span: 1;
        height: 100%;
    }}

    ChatPane {{
        column-span: 1;
        height: 100%;
    }}
    """

    BINDINGS = [
        Binding("ctrl+c",    "quit",           "Quit",         show=False, priority=True),
        Binding("ctrl+r",    "force_refresh",  "Refresh",      show=False, priority=True),
        Binding("ctrl+p",    "toggle_pause",   "Pause/Resume", show=False, priority=True),
        Binding("ctrl+n",    "open_network",   "Wi-Fi",        show=True,  priority=True),
        Binding("tab",       "focus_next",     "Next",         show=False),
        Binding("shift+tab", "focus_previous", "Prev",         show=False),
        Binding("escape",    "focus_input",    "→ Input",      show=False),
    ]

    _is_paused:     bool = False
    _connected:     bool = False
    _current_route: str  = "Local"
    _current_model: str  = LOCAL_MODELS[0][1]
    _suppress_model_event: bool = False  # guard against programmatic Select.Changed

    def compose(self) -> ComposeResult:
        yield YantraHeader()
        yield StatusFooter()
        with Container(id="main-body"):
            yield LeftPane()
            yield ThoughtStream()
            yield ChatPane()

    def on_mount(self) -> None:
        # Boot banner into ThoughtStream
        ts = self.query_one(ThoughtStream)
        for line in BOOT_BANNER.split("\n"):
            ts.write(line)
        ts.write(f"[{TEXT_DIM}]{'─' * 62}[/]")

        # Start background workers
        self.set_interval(POLL_INTERVAL, self._poll_telemetry)
        self._poll_telemetry()
        self._stream_logs()

        # Default focus → command input
        self.query_one("#chat-input", Input).focus()

    # ── Select change handlers ────────────────────────────────────────────────

    @on(Select.Changed, "#route-select")
    def _on_route_change(self, event: Select.Changed) -> None:
        new_route = str(event.value)
        self._current_route = new_route

        model_select = self.query_one("#model-select", Select)
        if new_route == "Cloud":
            opts      = [(f"  {n}", v) for n, v in CLOUD_MODELS]
            new_model = CLOUD_MODELS[0][1]
        else:
            opts      = [(f"  {n}", v) for n, v in LOCAL_MODELS]
            new_model = LOCAL_MODELS[0][1]

        # Suppress the spurious Select.Changed that fires when we set options/value
        self._suppress_model_event = True
        model_select.set_options(opts)
        model_select.value   = new_model
        self._suppress_model_event = False

        self._current_model  = new_model
        self._update_footer(new_model, new_route)
        self._ipc_send({"action": "set_model", "route": new_route, "model": new_model})

        chat = self.query_one(ChatPane)
        route_col = CYBER_CYAN if new_route == "Cloud" else ACID_GREEN
        chat.write_info(
            f"[{TEXT_DIM}]{_ts()}[/]  "
            f"[{AMBER}]◈  Route → [{route_col} bold]{new_route}[/][{AMBER}]"
            f"  |  Model → [{HEADER_GLOW} bold]{new_model}[/][{AMBER}][/]"
        )

    @on(Select.Changed, "#model-select")
    def _on_model_change(self, event: Select.Changed) -> None:
        if self._suppress_model_event:
            return  # Fired by _on_route_change — ignore
        new_model            = str(event.value)
        self._current_model  = new_model

        self._update_footer(new_model, self._current_route)
        self._ipc_send({"action": "set_model", "route": self._current_route, "model": new_model})

        chat = self.query_one(ChatPane)
        chat.write_info(
            f"[{TEXT_DIM}]{_ts()}[/]  "
            f"[{AMBER}]◈  Model → [{HEADER_GLOW} bold]{new_model}[/][{AMBER}][/]"
        )

    def _update_footer(self, model: str, route: str) -> None:
        footer = self.query_one(StatusFooter)
        footer.model = model
        footer.route = route

    # ── Button handlers ───────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-resume")   # type: ignore[misc]
    def _btn_resume(self) -> None: self._ipc_send({"action": "resume"})

    @on(Button.Pressed, "#btn-pause")    # type: ignore[misc]
    def _btn_pause(self) -> None: self._ipc_send({"action": "pause"})

    @on(Button.Pressed, "#btn-ping")     # type: ignore[misc]
    def _btn_ping(self) -> None: self._ipc_send({"action": "ping"})

    @on(Button.Pressed, "#btn-shutdown") # type: ignore[misc]
    def _btn_shutdown(self) -> None: self._ipc_send({"action": "shutdown"})

    # ── Input submission ──────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Scope strictly to the main chat input — do NOT capture PasswordModal input
        if event.input.id != "chat-input":
            return
        raw = event.value.strip()
        event.input.clear()
        event.input.focus()
        if not raw:
            return
        self.query_one(ChatPane).write_user(raw)
        self._handle_command(raw)

    @work(thread=True, name="cmd-parse")
    def _handle_command(self, raw: str) -> None:
        chat  = self.query_one(ChatPane)
        lower = raw.lower().strip()

        if lower == "help":
            self.app.call_from_thread(
                chat.write_info,
                f"[{CYBER_CYAN}]┌─ COMMANDS ────────────────────────────────────────[/]\n"
                f"[{CYBER_CYAN}]│[/] [{TEXT_BRIGHT}]pause[/]           Pause Kriya Loop\n"
                f"[{CYBER_CYAN}]│[/] [{TEXT_BRIGHT}]resume[/]          Resume Kriya Loop\n"
                f"[{CYBER_CYAN}]│[/] [{TEXT_BRIGHT}]install_os[/]      Launch Bare-Metal BTRFS Installer\n"
                f"[{CYBER_CYAN}]│[/] [{TEXT_BRIGHT}]inject <cmd>[/]    Inject command into REASON phase\n"
                f"[{CYBER_CYAN}]│[/] [{TEXT_BRIGHT}]ping[/]            Daemon roundtrip latency check\n"
                f"[{CYBER_CYAN}]│[/] [{TEXT_BRIGHT}]get_phase[/]       Show current Kriya phase\n"
                f"[{CYBER_CYAN}]│[/] [{TEXT_BRIGHT}]shutdown[/]        Request daemon shutdown\n"
                f"[{CYBER_CYAN}]│[/]\n"
                f"[{CYBER_CYAN}]│[/] [{TEXT_DIM}]Use Route + Model dropdowns on the left[/]\n"
                f"[{CYBER_CYAN}]│[/] [{TEXT_DIM}]to change the AI engine without restart.[/]\n"
                f"[{CYBER_CYAN}]└───────────────────────────────────────────────────[/]",
            )
            return

        if lower in ("pause", "resume"):
            self.call_from_thread(self._ipc_send, {"action": f"{lower}_loop"})
            return

        if lower in ("ping", "get_phase", "shutdown"):
            self.call_from_thread(self._ipc_send, {"action": lower})
            return

        if lower == "install_os":
            self.call_from_thread(
                self._ipc_send,
                {"action": "inject_thought", "payload": "install_os"}
            )
            return

        if lower.startswith("inject "):
            payload = raw[len("inject "):].strip()
            if not payload:
                self.call_from_thread(
                    chat.write_system,
                    f"[{AMBER}]⚠  Usage: inject <command>[/]",
                )
                return
            self.call_from_thread(
                self._ipc_send,
                {"action": "inject_thought", "payload": payload},
            )
            return

        self.call_from_thread(
            chat.write_system,
            f"[{AMBER}]⚠  Unknown: [{TEXT_BRIGHT}]{raw}[/]. "
            f"Type [{CYBER_CYAN}]help[/][{AMBER}].[/]",
        )

    # ── Telemetry poll (async) ───────────────────────────────────────────────

    @work(exclusive=True, name="telemetry-poll")
    async def _poll_telemetry(self) -> None:
        left   = self.query_one(LeftPane)
        header = self.query_one(YantraHeader)
        ts_log = self.query_one(ThoughtStream)
        footer = self.query_one(StatusFooter)

        try:
            data = await _uds_get("/telemetry")

            raw_phase  = str(data.get("phase", "UNKNOWN")).upper()
            phase      = raw_phase.split(".")[-1] if "." in raw_phase else raw_phase
            iteration  = int(data.get("iteration",    0))
            vram_used  = float(data.get("vram_used_gb",  0.0))
            vram_tot   = float(data.get("vram_total_gb", 0.0))
            gpu_util   = float(data.get("gpu_util_pct",  0.0))
            cpu_pct    = float(data.get("cpu_pct",       0.0))
            disk_free  = float(data.get("disk_free_gb",  0.0))
            model      = str(data.get("active_model",       "—"))
            routing    = str(data.get("inference_routing", "LOCAL"))

            def _apply(
                p=phase, i=iteration, vu=vram_used, vt=vram_tot,
                gu=gpu_util, cp=cpu_pct, df=disk_free, m=model, r=routing,
            ) -> None:
                left.phase     = p
                left.iteration = i
                left.vram_used = vu
                left.vram_tot  = vt
                left.gpu_util  = gu
                left.cpu_pct   = cp
                left.disk_free = df
                left.model     = m
                left.routing   = r
                left.connected = True
                left.is_paused = self._is_paused
                header.connected = True
                header.paused    = self._is_paused
                header.iteration = i
                header.phase     = p
                ts_log.set_phase(p)
                footer.model  = m
                footer.route  = r
                footer.status = "PAUSED" if self._is_paused else "LIVE"

            _apply()
            self._connected = True

        except (ConnectionRefusedError, FileNotFoundError, OSError):
            self._connected = False

            def _offline() -> None:
                left.connected  = False
                left.phase      = "[#FFB000] IPC DEGRADED ⚠[/]"
                header.connected = False
                header.phase     = "[#FFB000] IPC DEGRADED ⚠[/]"
                footer.status    = "AWAIT"

            _offline()

        except Exception as exc:  # noqa: BLE001
            ts_log.write(
                f"[{TEXT_DIM}]{_ts()}[/]  [{AMBER}]⚠  Telemetry: {exc}[/]",
            )

    # ── SSE ThoughtStream (async) ────────────────────────────────────────────

    @work(exclusive=True, name="stream-logs")
    async def _stream_logs(self) -> None:
        ts_log = self.query_one(ThoughtStream)
        header = self.query_one(YantraHeader)
        last_iter = 0

        while True:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(UDS_PATH), timeout=30.0
                )
                writer.write(
                    b"GET /stream HTTP/1.0\r\n"
                    b"Host: localhost\r\n"
                    b"Accept: text/event-stream\r\n"
                    b"Connection: keep-alive\r\n\r\n"
                )
                await writer.drain()

                buf = b""
                while b"\r\n\r\n" not in buf:
                    c = await reader.read(256)
                    if not c:
                        break
                    buf += c
                _, _, remainder = buf.partition(b"\r\n\r\n")

                line_buf = remainder.decode(errors="replace")
                while True:
                    raw_chunk = await reader.read(4096)
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
                            if not msg:
                                continue
                            ts       = _ts()
                            coloured = _colorize_log(msg)
                            ts_log.write(
                                f"[{TEXT_DIM}]{ts}[/]  {coloured}",
                            )
                            # Flash header on new iteration
                            if "ITERATION #" in msg.upper() or "ITERATION" in msg.upper():
                                header.flash_iteration()
                        except json.JSONDecodeError:
                            pass

            except (ConnectionRefusedError, FileNotFoundError, OSError):
                await asyncio.sleep(RECONNECT_DELAY)
                continue
            except Exception:  # noqa: BLE001
                await asyncio.sleep(RECONNECT_DELAY)
                continue

    # ── IPC dispatcher (async) ───────────────────────────────────────────────

    @work(name="ipc-post")
    async def _ipc_send(self, body: dict) -> None:
        chat = self.query_one(ChatPane)
        left = self.query_one(LeftPane)
        try:
            resp     = await _uds_post("/command", body)
            resp_str = json.dumps(resp, separators=(",", ":"))

            action = body.get("action", "")
            if action == "pause_loop":
                self._is_paused = True
                self._sync_pause()
            elif action == "resume_loop":
                self._is_paused = False
                self._sync_pause()

            chat.write_system(f"[{ACID_GREEN}]{resp_str}[/]")
            left.update_resp(resp_str)

        except (ConnectionRefusedError, FileNotFoundError, OSError):
            chat.write_system(
                f"[{AMBER}]⚠  Daemon not reachable — command dropped.[/]",
            )
        except Exception as exc:  # noqa: BLE001
            chat.write_system(
                f"[{CRIMSON}]✖  Failed: {exc}[/]",
            )

    def _sync_pause(self) -> None:
        left   = self.query_one(LeftPane)
        header = self.query_one(YantraHeader)
        footer = self.query_one(StatusFooter)
        left.is_paused   = self._is_paused
        header.paused    = self._is_paused
        footer.status    = "PAUSED" if self._is_paused else "LIVE"

    # ── Keyboard actions ──────────────────────────────────────────────────────

    async def action_quit(self) -> None:
        self.exit()

    async def action_force_refresh(self) -> None:
        self._poll_telemetry()

    async def action_toggle_pause(self) -> None:
        self._ipc_send({"action": "resume_loop" if self._is_paused else "pause_loop"})

    async def action_open_network(self) -> None:
        """Ctrl+N — push the Wi-Fi Network Manager modal."""
        await self.push_screen(NetworkModal())

    async def action_focus_input(self) -> None:
        self.query_one("#chat-input", Input).focus()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    YantraShell().run()
