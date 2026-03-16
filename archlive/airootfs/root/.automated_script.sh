#!/usr/bin/env bash
set -euo pipefail

LOG=/root/yantra-bootstrap.log
exec > >(tee -a "$LOG") 2>&1

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  YantraOS First-Boot Autopilot"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1) Ensure NetworkManager is running
if ! systemctl is-active --quiet NetworkManager; then
  echo "[YANTRA] Starting NetworkManager..."
  systemctl start NetworkManager
fi

# 2) Network connectivity check — launch nmtui on failure
if ! ping -c1 -W5 yantraos.com > /dev/null 2>&1; then
  echo "[YANTRA] Network not detected. Launching nmtui for Wi-Fi configuration..."
  nmtui || echo "[YANTRA] nmtui exited — continuing boot sequence."
fi

# 3) Ping the telemetry endpoint
echo "[YANTRA] Pinging telemetry health endpoint..."
if curl -fsSL https://yantraos.com/api/health > /dev/null 2>&1; then
  echo "[YANTRA] Telemetry endpoint OK — cloud inference available."
else
  echo "[YANTRA] Telemetry endpoint unreachable — offline mode."
fi

# 4) Wake up Docker Sandbox environment
if ! systemctl is-active --quiet docker; then
  echo "[YANTRA] Waking up Docker Sandbox environment..."
  systemctl start docker
fi

# 5) Enable and start Kriya Loop
if ! systemctl is-enabled --quiet yantra.service; then
  echo "[YANTRA] Enabling yantra.service..."
  systemctl enable yantra.service
fi

echo "[YANTRA] Starting Kriya Loop daemon..."
systemctl start yantra.service

sleep 2
systemctl --no-pager --full status yantra.service || true

# 6) Hand over to Pure TUI on TTY1
echo "[YANTRA] Launching Pure TUI for yantra_user on TTY1..."
mkdir -p /home/yantra_user
chown 1000:1000 /home/yantra_user

if [[ -z "${DISPLAY:-}" && $(tty) == /dev/tty1 ]]; then
    chown -R yantra_user:yantra_user /home/yantra_user
    chmod 700 /home/yantra_user
    chmod 666 /dev/tty1
    chmod 777 /run/yantra
    chmod 666 /run/yantra/ipc.sock || true
    exec su - yantra_user -c "cd /opt/yantra && TERM=linux COLORTERM=truecolor /opt/yantra/venv/bin/python3 -m core.tui_shell < /dev/tty1 > /dev/tty1 2>&1"
fi

# 7) Disable self on next boot (live session only)
rm -f /root/.automated_script.sh
