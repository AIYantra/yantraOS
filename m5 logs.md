Terminal 1: [admin@archlinux ~]$ cd /home/admin/yantra_workspace/YantraOS

systemctl is-active --quiet ydotoold.service || sudo systemctl start ydotoold.service

set -a
source .env
set +a

export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export YDOTOOL_SOCKET="/tmp/.ydotool_socket"
export YDOTOOL_POINTER_SCALE="2.0"

sudo --preserve-env=AZURE_OPENAI_API_KEY,AZURE_OPENAI_ENDPOINT,AZURE_OPENAI_DEPLOYMENT_NAME,AZURE_DEPLOYMENT_SOL,WAYLAND_DISPLAY,XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS,YDOTOOL_SOCKET,YDOTOOL_POINTER_SCALE \
  venv/bin/python -m core.host_executor
2026-07-15T19:40:21 INFO yantra.host_executor — > EXECUTOR: YantraOS Host Executor daemon starting...
2026-07-15T19:40:21 INFO yantra.host_executor — > EXECUTOR: PID=30050 UID=0 GID=0
2026-07-15T19:40:21 INFO yantra.host_executor — > EXECUTOR: Computer-use environment — azure_key=SET endpoint=SET deployment=SET wayland=SET runtime_dir=SET ydotool=SET
2026-07-15T19:40:21 INFO yantra.host_executor — > EXECUTOR: Removing stale socket /run/yantra/executor.sock
2026-07-15T19:40:21 INFO yantra.host_executor — > EXECUTOR: Socket permissions set — /run/yantra/executor.sock root:admin's primary group (gid=1000) 0o660
2026-07-15T19:40:21 INFO yantra.host_executor — > EXECUTOR: Listening on /run/yantra/executor.sock
2026-07-15T19:40:21 INFO yantra.host_executor — > EXECUTOR: Valid intents: ['BLOCK_IP', 'DISABLE_DAEMON', 'ENABLE_DAEMON', 'EXTERNAL_ACTION', 'PRUNE_SNAPSHOTS', 'RELOAD_DAEMON_CONFIGS', 'RESTART_DAEMON', 'STOP_DAEMON', 'SYNC_CLOCK', 'SYSTEM_UPDATE']
2026-07-15T19:40:55 INFO yantra.host_executor — > EXECUTOR: Client connected — unknown
2026-07-15T19:40:55 INFO yantra.host_executor — > EXECUTOR: Processing intent=EXTERNAL_ACTION target=
2026-07-15T19:40:55 INFO yantra.host_executor — > EXECUTOR: Triggering BTRFS pre-flight snapshot...
2026-07-15T19:40:55 WARNING yantra.host_executor — > EXECUTOR: Snapshot wrapper missing at /usr/bin/yantra-snapshot; using packaged snapshot module via explicit argv.
2026-07-15T19:40:55 INFO yantra.host_executor — > EXECUTOR: Pre-flight snapshot succeeded: NO_BTRFS: Root filesystem is not BTRFS — snapshot not applicable.
PRE-FLIGHT: PASSED (non-BTRFS filesystem)
2026-07-15T19:40:55 INFO yantra.host_executor — > EXECUTOR: Pre-flight snapshot gate PASSED.
2026-07-15T19:40:55 INFO yantra.host_executor — > EXECUTOR: Validated EXTERNAL_ACTION — External action: file_management
2026-07-15T19:40:55 INFO yantra.host_executor — > EXECUTOR: Client disconnected — unknown
2026-07-15T19:41:00 INFO yantra.host_executor — > EXECUTOR: Client connected — unknown
2026-07-15T19:41:00 INFO yantra.host_executor — > EXECUTOR: Processing intent=EXTERNAL_ACTION target=
2026-07-15T19:41:00 INFO yantra.host_executor — > EXECUTOR: Triggering BTRFS pre-flight snapshot...
2026-07-15T19:41:00 WARNING yantra.host_executor — > EXECUTOR: Snapshot wrapper missing at /usr/bin/yantra-snapshot; using packaged snapshot module via explicit argv.
2026-07-15T19:41:00 INFO yantra.host_executor — > EXECUTOR: Pre-flight snapshot succeeded: NO_BTRFS: Root filesystem is not BTRFS — snapshot not applicable.
PRE-FLIGHT: PASSED (non-BTRFS filesystem)
2026-07-15T19:41:00 INFO yantra.host_executor — > EXECUTOR: Pre-flight snapshot gate PASSED.
2026-07-15T19:41:00 INFO yantra.host_executor — > EXECUTOR: Validated EXTERNAL_ACTION — External action: file_management
2026-07-15T19:41:00 INFO yantra.host_executor — > EXECUTOR: Dispatching EXTERNAL_ACTION — External action: file_management
2026-07-15T19:41:00 INFO yantra.host_executor — > EXECUTOR: Running computer-use bridge in desktop session as admin (uid=1000 gid=1000).
2026-07-15T19:46:00 ERROR yantra.host_executor — > EXECUTOR: EXTERNAL_ACTION 'file_management' FAILED (300.16s)
  detail: EXTERNAL_ACTION timed out after 300s.
2026-07-15T19:46:00 INFO yantra.host_executor — > EXECUTOR: Client disconnected — unknown

Terminal #2: [admin@archlinux YantraOS]$ cd /home/admin/yantra_workspace/YantraOS
source venv/bin/activate

venv/bin/python - <<'PY'
import json
import socket
import time
from pathlib import Path

SOCKET = "/run/yantra/executor.sock"
filename = f"yantra_test_{int(time.time())}.txt"
content = "Created by the YantraOS M5 manual test.\n"

payload = {
    "intent": "EXTERNAL_ACTION",
    "target": "",
    "action_payload": {
        "action": "file_management",
        "operation": "create",
        "path": filename,
        "content": content,
    },
}

def send(data):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(310)
        client.connect(SOCKET)
        client.sendall((json.dumps(data) + "\n").encode())

        response = b""
        while b"\n" not in response:
            chunk = client.recv(4096)
            if not chunk:
                raise RuntimeError("Executor closed without a response")
            response += chunk

    return json.loads(response.splitlines()[0])

response = send(payload)
print(json.dumps(response, indent=2))

if response["status"] == "CONFIRMATION_REQUIRED":
    print("Type APPROVE within 120 seconds:")

    with open("/dev/tty", encoding="utf-8") as tty:
        approved = tty.readline().strip() == "APPROVE"

    payload["confirmation"] = {
        "token": response["confirmation_token"],
        "approved": approved,
    }

    response = send(payload)
    print(json.dumps(response, indent=2))

path = Path.home() / "Documents" / "YantraOS" / filename
print(f"\nExpected file: {path}")
print(f"Exists: {path.exists()}")

if path.exists():
    print(f"Mode: {oct(path.parent.stat().st_mode & 0o777)}")
    print(f"Content: {path.read_text(encoding='utf-8')!r}")
PY
{
  "status": "CONFIRMATION_REQUIRED",
  "intent": "EXTERNAL_ACTION",
  "action_type": "file_management",
  "confirmation_token": "b40a6f1680bb3bcc770352d56261fdc4e7adbcd19f08c23a79f741d3a761607d",
  "run_number": 9,
  "confirmation_threshold": 20,
  "confirmation_reason": "first_20_runs",
  "expires_in_secs": 120,
  "ts": 1784124655.275156
}
Type APPROVE within 120 seconds:
APPROVE
{
  "status": "FAILURE",
  "intent": "EXTERNAL_ACTION",
  "action_type": "file_management",
  "description": "External action: file_management",
  "error": "EXTERNAL_ACTION timed out after 300s.",
  "stdout": "",
  "stderr": "EXTERNAL_ACTION timed out after 300s.",
  "elapsed_secs": 300.163,
  "ts": 1784124960.253709
}

Expected file: /home/admin/Documents/YantraOS/yantra_test_1784124655.txt
Exists: False
(venv) [admin@archlinux YantraOS]$
