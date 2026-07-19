# M5 File Management Manual Test

This test lets a normal user manage files with plain English. GPT-5.6 Sol translates the sentence into a typed `file_management` action, and the Host Executor applies confirmation, audit, path, and safety checks before anything runs.

You do not need to write or edit JSON. Only edit the human sentence inside quotes in the commands below.

Do not use `ui.gui_shell` for this test yet. It currently submits the generic `computer_use_task` action rather than the typed M5 payload.

## 1. Start the Host Executor

Open Terminal 1 and run:

```bash
cd /home/admin/yantra_workspace/YantraOS

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
```

Leave Terminal 1 running.

If an older host executor is already running, stop it with `Ctrl+C` and start it again so it loads the current timeout diagnostics.

## 2. Use a Plain-English Command

Open Terminal 2 and run:

```bash
cd /home/admin/yantra_workspace/YantraOS
source venv/bin/activate

venv/bin/python -m core.yantra_core \
  "Create a Markdown file named M5-human-command-01.md containing exactly: Created from a plain English YantraOS command."
```

When asked to confirm, type `y` and press Enter.

The normal command format is:

```bash
venv/bin/python -m core.yantra_core "YOUR NORMAL HUMAN COMMAND"
```

Edit only `YOUR NORMAL HUMAN COMMAND`.

### Create

```bash
venv/bin/python -m core.yantra_core \
  "Create a Markdown file named M5-human-command-02.md containing exactly: This file was requested in normal human language."
```

### Read

```bash
venv/bin/python -m core.yantra_core \
  "Read the file M5-human-command-02.md and show me its exact contents."
```

### Move

```bash
venv/bin/python -m core.yantra_core \
  "Move M5-human-command-02.md to M5-human-command-moved.md."
```

Other valid examples include:

```text
Read the file M5-human-command-01.md.
Move M5-human-command-01.md to M5-human-command-moved.md.
Create a text file named shopping-list.txt containing exactly: milk, rice, and tea.
```

Use a new filename for each create command because overwrites are blocked. All paths are relative to `~/Documents/YantraOS`. Deletion is disabled.

For create operations, the bridge writes the validated file exclusively with mode `0600`, then GPT-5.6 Sol visually verifies that Dolphin lists it. Sol cannot overwrite an existing file.

For multi-step commands, later actions run only after the previous action succeeds. Desktop actions such as opening Telegram now run through the Host Executor too, so they inherit the verified Wayland and ydotool environment.

## 3. Verify the Plain-English Create

After the create command succeeds, run:

```bash
stat -c 'owner=%U:%G mode=%a path=%n' \
  "$HOME/Documents/YantraOS/M5-human-command-01.md"

cat "$HOME/Documents/YantraOS/M5-human-command-01.md"
```

Expected output includes:

```text
owner=admin:admin mode=600
Created from a plain English YantraOS command.
```

## 4. Developer-Only JSON Diagnostic

Normal users should skip this section. Use it only when debugging the raw executor protocol.

Open Terminal 2 and run:

```bash
cd /home/admin/yantra_workspace/YantraOS
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
    print(f"Managed root mode: {oct(path.parent.stat().st_mode & 0o777)}")
    print(f"File mode: {oct(path.stat().st_mode & 0o777)}")
    print(f"Content: {path.read_text(encoding='utf-8')!r}")
PY
```

When prompted, type exactly:

```text
APPROVE
```

## 5. Expected Result

Dolphin should open at `~/Documents/YantraOS`. The bridge securely creates a uniquely named mode-`0600` file without overwriting anything, then GPT-5.6 Sol visually verifies that it is listed in Dolphin.

The final output should include:

```text
"status": "SUCCESS"
Exists: True
Managed root mode: 0o700
File mode: 0o600
Content: 'Created by the YantraOS M5 manual test.\n'
```

Deletion, absolute paths, hidden paths, traversal, symlink escapes, right-click menus, and overwrites remain blocked by policy.

M5 model calls have a 60-second deadline, no automatic SDK retries, a 20-step cap, and a 210-second file bridge deadline. General desktop actions have a bounded 420-second executor deadline. Timeout responses preserve partial bridge logs so the last completed step remains visible.

The focused M5 and integration checks currently pass: 63 tests.

## 6. Stop the Executor

Return to Terminal 1 and press `Ctrl+C`.
