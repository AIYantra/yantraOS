# /etc/profile.d/yantra_kiosk.sh

# Only execute on the primary physical console (tty1)
if [ "$(tty)" = "/dev/tty1" ]; then
    # Force colors for the framebuffer
    export TERM=linux
    export COLORTERM=truecolor
    
    # Execute the Yantra Shell directly to the screen
    /opt/yantra/venv/bin/python3 /opt/yantra/core/tui_shell.py
fi
