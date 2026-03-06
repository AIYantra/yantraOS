# YantraOS QA Final Report — Boot Fix & TUI Verification

**Date:** 2026-03-05  
**ISO:** `yantraos-2026.03.05-x86_64.iso` (1.5 GB)  
**Status:** ✅ **PASS — TUI boots successfully**

---

## Root Cause Analysis

### Bug 1: Kernel Freeze at EDD Probe

**Symptom:** ISO stuck at `Probing EDD (edd=off to disable)... ok` indefinitely.

**Root Cause:** The BIOS Enhanced Disk Drive (EDD) probe hangs in QEMU's virtualized firmware. The kernel's KMS (Kernel Mode Setting) driver also attempts GPU framebuffer initialization, which further stalls boot in a headless/virtual environment.

**Fix:** Injected `edd=off nomodeset` into **all** kernel command lines across 6 bootloader config files:

| File | Lines Patched |
|------|---------------|
| `syslinux/archiso_sys-linux.cfg` | 2 APPEND lines |
| `syslinux/archiso_pxe-linux.cfg` | 3 APPEND lines |
| `grub/grub.cfg` | 2 linux lines |
| `grub/loopback.cfg` | 2 linux lines |
| `efiboot/loader/entries/01-archiso-linux.conf` | 1 options line |
| `efiboot/loader/entries/02-archiso-speech-linux.conf` | 1 options line |

Also added `console=ttyS0,115200` to GRUB and efiboot entries for serial console output.

### Bug 2: TUI Crash — Missing `textual` Module

**Symptom:** (Discovered during QA Loop Iteration 1)  
```
File "/opt/yantra/core/tui_shell.py", line 15, in <module>
    from textual import work
ModuleNotFoundError: No module named 'textual'
```

**Root Cause:** `tui_shell.py` imports from the `textual` framework, but `textual` and `rich` were not listed in `compile_iso.sh`'s `PIP_REQUIREMENTS` array. Additionally, the file was owned by `root:root` (set by the build script's `chown -R root:root` in Phase 5), which caused the initial edit attempt to silently fail.

**Fix:**
1. Changed ownership: `sudo chown admin:admin compile_iso.sh`
2. Added to `PIP_REQUIREMENTS`:
   ```bash
   "textual>=0.50.0"
   "rich>=13.0.0"
   ```

---

## Verification Evidence

### QA Loop Iteration 1 (EDD fix only)
- ✅ Kernel loaded `vmlinuz-linux` and `initramfs-linux.img`
- ✅ Kernel passed EDD probe (no freeze)
- ✅ systemd booted to multi-user target
- ❌ TUI crashed: `ModuleNotFoundError: No module named 'textual'`

### QA Loop Iteration 2 (EDD fix + textual dependency)
- ✅ Kernel loaded and passed EDD probe
- ✅ systemd booted all services
- ✅ `YantraOS Kriya Loop Daemon` started
- ✅ **`tui_shell.py` running on tty1** (PID 633, `Sl+` state)
- ✅ **TUI rendering ANSI escape codes** — serial output captured:
  ```
  ─────────────────────────────────────┐
  [09:42:05]  AWAITING DAEMON CONNECTION…  /run/yantra/ipc.sock
  [09:42:08]  AWAITING DAEMON CONNECTION…  /run/yantra/ipc.sock
  ```
- ✅ No crash log (`/tmp/tui_crash.log` empty)
- ✅ `daemon.py` also running (PID 655)

### Process Table Snapshot
```
yantra_+  633  11.2  1.0  345784  41752  tty1  Sl+  /opt/yantra/venv/bin/python3 /opt/yantra/core/tui_shell.py
yantra_+  655   1.2  0.2   15508  11164  ?     Rs   /opt/yantra/venv/bin/python3 /opt/yantra/core/daemon.py
```

---

## Files Modified

| File | Change |
|------|--------|
| `archlive/syslinux/archiso_sys-linux.cfg` | Added `edd=off nomodeset` to 2 APPEND lines |
| `archlive/syslinux/archiso_pxe-linux.cfg` | Added `edd=off nomodeset` to 3 APPEND lines |
| `archlive/grub/grub.cfg` | Added `edd=off nomodeset console=ttyS0,115200` to 2 linux lines |
| `archlive/grub/loopback.cfg` | Added `edd=off nomodeset console=ttyS0,115200` to 2 linux lines |
| `archlive/efiboot/loader/entries/01-archiso-linux.conf` | Added `edd=off nomodeset console=ttyS0,115200` |
| `archlive/efiboot/loader/entries/02-archiso-speech-linux.conf` | Added `edd=off nomodeset console=ttyS0,115200` |
| `archlive/compile_iso.sh` | Added `textual>=0.50.0` and `rich>=13.0.0` to PIP_REQUIREMENTS |

---

## QEMU Command Used
```bash
qemu-system-x86_64 -enable-kvm -m 4G -nographic \
  -cdrom archlive/out/yantraos-2026.03.05-x86_64.iso
```

> **Note:** `-nographic` already redirects serial to stdio — do **not** add `-serial stdio` (causes conflict).
