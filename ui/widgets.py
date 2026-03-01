"""
YantraOS — UI Widgets
Model Route: Claude Opus 4.6

Specific TUI components for the Yantra Shell.
Widgets:
- GPUHealth: Displays real-time hardware telemetry (VRAM, Util, Temps).
- ThoughtStream: Shows the real-time reasoning and Kriya Loop states of the daemon.
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll, Vertical
from textual.widget import Widget
from textual.widgets import Static, Label

class GPUHealth(Widget):
    """Displays critical GPU and hardware health metrics."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stats_container = Vertical()

    def compose(self) -> ComposeResult:
        yield Label("[#888888]HARDWARE TELEMETRY[/]", classes="pane-title")
        yield self.stats_container

    def update_stats(self, telemetry: dict) -> None:
        """Update the widget with fresh telemetry from the daemon."""
        # Clear existing
        self.stats_container.query(Static).remove()
        
        gpus = telemetry.get("gpus", {})
        if not gpus:
            self.stats_container.mount(Label("No GPU Data", classes="gpu-alert"))
            return

        for gpu_id, stat in gpus.items():
            if "error" in stat:
                self.stats_container.mount(Label(stat["error"], classes="gpu-alert"))
                continue

            name = stat.get("name", "Unknown GPU")
            vram_total = stat.get("vram_total_mb", 0)
            vram_used = stat.get("vram_used_mb", 0)
            util = stat.get("utilization", 0)
            temp = stat.get("temp_c", 0)
            power = stat.get("power_w", 0.0)

            pct = (vram_used / vram_total * 100) if vram_total else 0
            vram_color = "[#FFB000]" if pct > 85 else "[#00E5FF]"
            
            self.stats_container.mount(Label(f"[#888888][{gpu_id}] {name}[/]", classes="gpu-stat-label"))
            self.stats_container.mount(Static(
                f"[#888888]Util: [/][#00E5FF]{util}%[/][#888888] | Temp: [/][#00E5FF]{temp}°C[/]"
            ))
            self.stats_container.mount(Static(
                f"[#888888]VRAM: [/]{vram_color}{vram_used} / {vram_total} MB[/]"
            ))
            self.stats_container.mount(Static(
                f"[#888888]Pwr : [/][#00E5FF]{power:.1f}W[/]"
            ))
            self.stats_container.mount(Static("")) # Spacer

        # Add Engine status
        status = telemetry.get("daemon_status", "UNKNOWN")
        phase = telemetry.get("current_cycle", {}).get("phase", "NONE")
        
        self.stats_container.mount(Label("[#888888]ENGINE STATUS[/]", classes="pane-title"))
        status_color = "[#FFB000]" if status == "ERROR" else "[#00E5FF]"
        self.stats_container.mount(Static(
            f"[#888888]Daemon: [/]{status_color}{status}[/]"
        ))
        self.stats_container.mount(Static(
            f"[#888888]Phase : [/][#00E5FF]{phase}[/]"
        ))

class ThoughtStream(Widget):
    """Displays the daemon's internal log tail / thoughts in the main pane."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.log_container = VerticalScroll(id="thought-scroll")

    def compose(self) -> ComposeResult:
        yield Label("[#888888]THOUGHT STREAM[/]", classes="pane-title")
        yield self.log_container

    def push_log(self, text: str) -> None:
        """Push a new log entry to the bottom of the stream."""
        if "[ERROR]" in text:
            text = text.replace("[ERROR]", "[#FFB000][ERROR][/]")
            classes = "log-entry-error"
        elif "[YANTRA]" in text or ">" in text:
            text = text.replace("[YANTRA]", "[#00E5FF][YANTRA][/]").replace(">", "[#00E5FF]>[/]")
            classes = "log-entry-info"
        else:
            text = f"[#888888]{text}[/]"
            classes = "log-entry"
            
        self.log_container.mount(Static(text, classes=classes))
        self.log_container.scroll_end(animate=False)

    def update_logs(self, log_lines: list[str]) -> None:
        """Replace all logs (from telemetry sync)."""
        # Only add new lines to avoid flickering
        # For simplicity in this iteration, we clear if there's a big mismatch
        # but a proper diff is better. We will just rewrite them safely.
        self.log_container.query(Static).remove()
        for line in log_lines:
            self.push_log(line)
