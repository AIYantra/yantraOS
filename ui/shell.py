"""
YantraOS — Shell Core
Model Route: Claude Opus 4.6

The main Textual application mapping the 3-pane structural layout and logic.
Adheres strictly to "The Geometric Law".
"""

import asyncio
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Input, Label
from textual.reactive import reactive

from .widgets import GPUHealth, ThoughtStream
from .bridge import IPCBridge

class TelemetryPane(Container):
    """Left pane: Hardware and status telemetry."""
    def compose(self) -> ComposeResult:
        yield GPUHealth(id="gpu-health")


class ThoughtStreamPane(Container):
    """Top-right pane: Real-time Kriya reasoning and logs."""
    def compose(self) -> ComposeResult:
        yield ThoughtStream(id="thought-stream")


class InteractionPane(Container):
    """Bottom-right pane: User input and command invocation."""
    def compose(self) -> ComposeResult:
        yield Label("YANTRA SHELL >", classes="pane-title")
        yield Input(placeholder="Input Directive...", id="cmd-input")


class YantraShell(App):
    """YantraOS Structural Textual Application."""
    
    CSS_PATH = "theme.tcss"
    TITLE = "YantraOS Shell"
    
    # Real-time data model
    telemetry = reactive({})
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bridge = IPCBridge()
        self._polling_task = None

    def compose(self) -> ComposeResult:
        yield TelemetryPane(id="telemetry-pane")
        yield ThoughtStreamPane(id="thought-stream-pane")
        yield InteractionPane(id="interaction-pane")

    async def on_mount(self) -> None:
        """Initialize IPC and start asynchronous polling."""
        # Focus the input automatically
        self.query_one("#cmd-input").focus()
        
        # Connect IPC
        connected = await self.bridge.connect()
        stream = self.query_one(ThoughtStream)
        
        if connected:
            stream.push_log("[YANTRA] Uplink established to Core Daemon.")
            # Start background polling
            self._polling_task = asyncio.create_task(self.poll_daemon())
        else:
            stream.push_log("[ERROR] Daemon offline. Telemetry inactive.")

    async def poll_daemon(self) -> None:
        """Background loop to fetch telemetry without blocking the UI."""
        while True:
            try:
                data = await self.bridge.fetch_telemetry()
                if data:
                    self.telemetry = data
            except Exception:
                pass
            await asyncio.sleep(1.0) # 1Hz refresh

    def watch_telemetry(self, old_telemetry: dict, new_telemetry: dict) -> None:
        """Reactive watcher: Update widgets when data arrives."""
        gpu_widget = self.query_one(GPUHealth)
        stream_widget = self.query_one(ThoughtStream)
        
        if new_telemetry:
            # Update telemetry
            gpu_widget.update_stats(new_telemetry)
            
            # Update logs if provided in telemetry snapshot
            logs = new_telemetry.get("logs", [])
            if logs:
                # Basic logic: append new logs
                # In production, we'd track a cursor ID. 
                # Doing a naive rewrite for the prototype.
                stream_widget.update_logs(logs)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user commands sent to the daemon."""
        cmd = event.value.strip()
        if not cmd:
            return
            
        stream = self.query_one(ThoughtStream)
        stream.push_log(f"> {cmd}")
        event.input.value = "" # Clear input
        
        if cmd.lower() in ["exit", "quit"]:
            self.exit()
            return
            
        # Send directive to daemon
        res = await self.bridge.send_command("directive", {"text": cmd})
        if "error" in res:
            stream.push_log(f"[ERROR] {res['error']}")
        else:
            stream.push_log(f"[YANTRA] ACK: {res.get('status', 'OK')}")

if __name__ == "__main__":
    app = YantraShell()
    app.run()
