"""
YantraOS — Fleet Manager (SSH Gateway)
Strictly whitelisted multi-node telemetry querying.
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import os
import stat

# We will use asyncssh for pure async networking in the Kriya loop.
try:
    import asyncssh
except ImportError:
    print("FATAL: asyncssh not found. Please install asyncssh.", file=sys.stderr)
    sys.exit(1)


# ── Configuration & Constraints ───────────────────────────────────────────────

NODES_INVENTORY = Path("/opt/yantra/config/nodes.json")

# SSH known_hosts file — NEVER set to None (MITM vulnerability).
# Operators must populate this file with host keys for each fleet node.
KNOWN_HOSTS_FILE = Path("/opt/yantra/config/known_hosts")

# The absolute maximum time an SSH session may take
SSH_TIMEOUT_SEC = 15.0

# Strict whitelist: The AI may ONLY send these exact strings 
# over the SSH pipe. Do not allow arbitary concatenation.
WHITELISTED_COMMANDS = {
    "uptime",
    "df -h",
    "free -m",
    "systemctl status",
    "systemctl status yantra.service",
    "sensors",
    "journalctl -u yantra.service -n 50 --no-pager",
    "ping -c 3 8.8.8.8",
}

def _init_permissions():
    """Permissions Pre-Flight Check"""
    if NODES_INVENTORY.exists():
        st = os.stat(NODES_INVENTORY)
        if stat.S_IMODE(st.st_mode) != 0o400:
            print(f"CRITICAL WARNING: {NODES_INVENTORY} has unsafe permissions. Enforcing 0400.", file=sys.stderr)
            os.chmod(NODES_INVENTORY, 0o400)

        try:
            raw = json.loads(NODES_INVENTORY.read_text("utf-8"))
            for ip, config in raw.items():
                key_path = Path(config.get("key", "/opt/yantra/config/id_yantra_fleet"))
                if key_path.exists():
                    st = os.stat(key_path)
                    if stat.S_IMODE(st.st_mode) != 0o400:
                        print(f"CRITICAL WARNING: SSH Key {key_path} has unsafe permissions. Enforcing 0400.", file=sys.stderr)
                        os.chmod(key_path, 0o400)
        except Exception:
            pass

_init_permissions()


# ── Internal Types ────────────────────────────────────────────────────────────

class FleetNode:
    """Represents a validated node from the inventory."""
    def __init__(self, ip: str, username: str, key_path: str):
        self.ip = ip
        self.username = username
        self.key_path = key_path

    def __repr__(self) -> str:
        return f"<FleetNode {self.ip} ({self.username})>"


# ── Inventory Management ──────────────────────────────────────────────────────

def _load_inventory() -> Dict[str, FleetNode]:
    """Read the inventory JSON and return a fast-lookup dictionary."""
    if not NODES_INVENTORY.exists():
        return {}

    try:
        raw = json.loads(NODES_INVENTORY.read_text("utf-8"))
        nodes = {}
        # Expecting format: { "192.168.1.10": {"user": "admin", "key": "/path"} }
        for ip, config in raw.items():
            nodes[ip] = FleetNode(
                ip=ip,
                username=config.get("user", "yantra"),
                key_path=config.get("key", "/opt/yantra/config/id_yantra_fleet")
            )
        return nodes
    except Exception as exc:
        print(f"WARN: Failed to parse fleet inventory {NODES_INVENTORY}: {exc}")
        return {}

def enumerate_fleet() -> List[str]:
    """Returns a list of all known node IPs."""
    nodes = _load_inventory()
    return list(nodes.keys())


# ── Secure Execution ──────────────────────────────────────────────────────────

async def query_node_telemetry(ip: str, command: str) -> Tuple[bool, str]:
    """
    Autonomously connects to the remote `ip` via SSH and executes `command`.
    Returns (success: bool, output: str).
    """
    if any(char in command for char in ('&', '|', ';', '$', '`', '>', '<')):
        return False, "SECURITY ERROR: Shell concatenation and variables are strictly prohibited."

    if command.strip() not in WHITELISTED_COMMANDS:
        return False, f"SECURITY ERROR: Command '{command}' is not in the telemetry whitelist."

    nodes = _load_inventory()
    if ip not in nodes:
        return False, f"ERROR: Node '{ip}' is not registered in the fleet inventory."

    node = nodes[ip]
    key_file = Path(node.key_path)
    if not key_file.exists():
        return False, f"ERROR: SSH Key {key_file} not found for node {ip}."

    # ── Resolve known_hosts policy ─────────────────────────────────────
    # SECURITY: Never set known_hosts=None — that disables host key
    # verification entirely, enabling trivial MITM attacks.
    known_hosts_arg: Any = str(KNOWN_HOSTS_FILE) if KNOWN_HOSTS_FILE.exists() else ()
    if not KNOWN_HOSTS_FILE.exists():
        print(
            f"SECURITY WARNING: {KNOWN_HOSTS_FILE} not found. "
            "SSH connections will REJECT unknown hosts. Populate this file "
            "with host keys for each fleet node.",
            file=sys.stderr,
        )

    try:
        async with asyncssh.connect(
            node.ip,
            username=node.username,
            client_keys=[str(key_file)],
            known_hosts=known_hosts_arg,
            connect_timeout=5,
        ) as conn:
            result = await asyncio.wait_for(
                conn.run(command, check=False),
                timeout=SSH_TIMEOUT_SEC,
            )

            if result.exit_status == 0:
                out = result.stdout.strip() if isinstance(result.stdout, str) else "[NO STDOUT]"
                if not out:
                    out = "[NO STDOUT]"
                return True, out
            else:
                err = result.stderr.strip() if isinstance(result.stderr, str) else "[NO STDERR]"
                if not err or err == "[NO STDERR]":
                    err = result.stdout.strip() if isinstance(result.stdout, str) else "[NO STDOUT]"
                return False, f"Remote execution failed (exit {result.exit_status}):\n{err}"

    except asyncio.TimeoutError:
        error_payload = json.dumps({
            "error": "TimeoutError",
            "message": "Edge node is degraded or unreachable.",
            "node_ip": ip,
        })
        return False, error_payload
    except asyncssh.Error as exc:
        return False, f"SSH ERROR: {exc}"
    except Exception as exc:
        return False, f"INTERNAL ERROR: {exc}"
