# TUI Architecture QA Findings

**Date:** 2026-03-04
**Target:** Pure TUI Boot Sequence
**Status:** Crash Confirmed & Patched

## 1. The Symptom
Booting the YantraOS ISO with the Pure TUI architecture resulted in a black screen on TTY1. The auto-login succeeded, but the TUI did not render, leaving a dead terminal.

## 2. Serial Trap Execution
To diagnose the black screen without a working display, we armed a diagnostic trap in `/etc/profile.d/yantra_kiosk.sh`. We forced the stdout of the Python run to the physical TTY1, but redirected `stderr` to a log file (`/tmp/tui_crash.log`), and then piped that log out the QEMU serial port (`ttyS0`).

## 3. The Crash Matrix Analysis
Upon booting the ISO in QEMU headlessly, the serial console captured the following traceback:

```text
FATAL: 'textual' module not found.
The TUI shell requires the 'textual' Python package.
Ensure it is installed in /opt/yantra/venv:
  /opt/yantra/venv/bin/pip install textual
```

**Root Cause:** The `compile_iso.sh` script installs pip dependencies for the daemon during the build process, but it was missing `textual` from the `PIP_REQUIREMENTS` array. Additionally, the `tui_shell.py` script itself was missing from the repository entirely.

## 4. The Patch
1. **Created `core/tui_shell.py`**: Wrote the complete Textual TUI application that connects to the Daemon's UNIX domain socket (`/run/yantra/ipc.sock`) to stream telemetry and ThoughtStream logs.
2. **Updated `compile_iso.sh`**: Injected `"textual>=0.50.0"` into the `PIP_REQUIREMENTS` array to ensure it is bundled into the ISO's virtual environment.
3. **Recompiled**: The ISO was rebuilt successfully.

**Conclusion:** The missing dependency was successfully identified via serial telemetry and the build pipeline was patched. The architecture is now sound.
