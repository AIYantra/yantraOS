# ~/.bash_profile — YantraOS root auto-login profile
# Source global profile.d scripts (including yantra_kiosk.sh)
if [ -d /etc/profile.d ]; then
    for f in /etc/profile.d/*.sh; do
        [ -r "$f" ] && . "$f"
    done
fi

# YantraOS Auto-Ignition Sequence
if [[ "$(tty)" == "/dev/tty1" ]]; then
    echo "[YANTRA] Igniting Control Center..."
    exec /opt/yantra/venv/bin/python3 /opt/yantra/core/tui_shell.py
fi
