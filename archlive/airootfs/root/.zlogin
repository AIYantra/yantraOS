# YantraOS Absolute Auto-Ignition
if [[ "$(tty)" == "/dev/tty1" ]]; then
    echo "[YANTRA] Igniting Control Center..."
    exec /opt/yantra/venv/bin/python3 /opt/yantra/core/tui_shell.py
fi
