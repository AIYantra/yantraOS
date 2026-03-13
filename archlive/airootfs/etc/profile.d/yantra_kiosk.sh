#!/bin/bash
# /etc/profile.d/yantra_kiosk.sh
# YantraOS — Pure TUI Auto-Launch (tty1 only)
# No Wayland, no cage, no compositor. Pure framebuffer TUI.
#
# Using exec replaces the login shell entirely. When the user exits
# the TUI via Ctrl+C, it safely drops to a fresh login prompt instead
# of leaving a root shell open.

# YantraOS Auto-Ignition Sequence
if [[ "$(tty)" == "/dev/tty1" ]]; then
    echo "[YANTRA] Igniting Control Center..."
    exec /opt/yantra/venv/bin/python3 /opt/yantra/core/tui_shell.py
fi
