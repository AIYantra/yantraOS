"""
YantraOS — IPC Bridge (Phase 10: Cross-Platform)
Model Route: Claude Opus 4.6

Asynchronous IPC client connecting the Yantra Shell TUI to the Daemon.
- Linux:   UNIX Domain Sockets (/tmp/yantra.sock)
- Windows: TCP socket (127.0.0.1:50000)
"""

import asyncio
import json
import logging
import os

# IPC defaults (must match engine.py)
IPC_TCP_HOST = "127.0.0.1"
IPC_TCP_PORT = 50000
IPC_UDS_PATH = "/tmp/yantra.sock"


class IPCBridge:
    def __init__(
        self,
        socket_path: str = IPC_UDS_PATH,
        tcp_host: str = IPC_TCP_HOST,
        tcp_port: int = IPC_TCP_PORT,
    ):
        self.socket_path = socket_path
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self.reader = None
        self.writer = None
        self.connected = False
        self._is_windows = os.name == "nt"

    async def connect(self):
        """Establish asynchronous connection to the YantraOS daemon."""
        try:
            if self._is_windows:
                self.reader, self.writer = await asyncio.open_connection(
                    self.tcp_host, self.tcp_port
                )
                logging.info(f"IPC connected via TCP to {self.tcp_host}:{self.tcp_port}")
            else:
                self.reader, self.writer = await asyncio.open_unix_connection(
                    self.socket_path
                )
                logging.info(f"IPC connected via UDS to {self.socket_path}")

            self.connected = True
            return True
        except Exception as e:
            logging.error(f"IPC Connection failed: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """Close the socket connection."""
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
        self.connected = False
        self.reader = None
        self.writer = None

    async def send_command(self, action: str, payload: dict = None) -> dict:
        """Send a JSON command to the daemon and await response."""
        if not self.connected:
            await self.connect()
            if not self.connected:
                return {"error": "Not connected to daemon"}

        msg = {
            "action": action,
            "payload": payload or {}
        }

        try:
            data = json.dumps(msg).encode('utf-8')
            self.writer.write(data + b'\n')
            await self.writer.drain()

            # Wait for response
            response_data = await self.reader.readline()
            if not response_data:
                await self.disconnect()
                return {"error": "Connection lost"}

            return json.loads(response_data.decode('utf-8'))

        except Exception as e:
            await self.disconnect()
            return {"error": str(e)}

    async def fetch_telemetry(self) -> dict:
        """Fetch the latest telemetry snapshot from the daemon."""
        res = await self.send_command("get_telemetry")
        if "error" in res:
            return {}
        return res.get("data", {})
