# ~/.zprofile — YantraOS root auto-login profile (zsh variant)
# Arch Linux defaults to zsh for root, so this ensures coverage.

# YantraOS Auto-Ignition Sequence
if [[ "$(tty)" == "/dev/tty1" ]]; then
    echo "[YANTRA] Igniting Control Center..."
    exec /opt/yantra/venv/bin/python3 /opt/yantra/core/tui_shell.py
fi
