# YantraOS Day 9–14 Launch Roadmap (ArchISO, GPU Binding, Shell, Security, Onboarding, QA)

## Executive Overview

This document gives a concrete, Arch-centric execution plan for YantraOS Days 9–14: GPU driver packaging into `archiso`, real GPU binding for the Kriya Loop, kiosk shell design, systemd hardening for a non-root `yantra_daemon` (or `yantra-user`), first-boot onboarding using `/root/.automated_script.sh`, and final QA + distribution strategy.[^1]

The plan assumes the existing Kriya Loop Python daemon, systemd unit, and ArchISO build profile are already functional as described in `YANTRA_MASTER_CONTEXT.md`, including `deploy/systemd/yantra.service`, `archlive/profiledef.sh`, and `archlive/packages.x86_64`.[^1]

***

## Day 9 – GPU & Network: Binding the Metal

### 9.1 ArchISO GPU Driver Strategy (NVIDIA + AMD)

The constraint is to support NVIDIA proprietary + CUDA and AMD ROCm/AMDGPU without exploding ISO size (target ≤ 4–6 GB) while still booting on non-GPU and Intel-only systems.[^2][^3][^1]

Key principles:

- Include **kernel-side drivers + core stacks**, not full CUDA/ROCm dev suites.
- Use **modular packages** and `pacstrap`-style post-install hooks to pull optional heavyweight components (e.g., `cuda`, `cudnn`, ROCm meta-packages) only on capable hardware.[^3][^2]
- Rely on existing `hardware.py` VRAM/GPU detection and augment it to probe loaded kernel modules and vendor IDs (`lspci -nn`, `nvidia-smi`, `rocm-smi`).[^1]

#### 9.1.1 `archlive/packages.x86_64` GPU Segment (Minimal)

Augment your `archlive/packages.x86_64` with a **minimal** GPU baseline:

```text
# GPU base (kernel + utils)
linux
linux-headers
mesa

# NVIDIA runtime stack (no full CUDA toolchain here)
nvidia-dkms
nvidia-utils
lib32-nvidia-utils
opencl-nvidia     # gives OpenCL + basic runtime hooks

# AMD/Intel open stack
mesa-vdpau
vulkan-radeon
lib32-vulkan-radeon
vulkan-intel
lib32-vulkan-intel

# Optional: OpenCL for AMD via official repos
rocm-opencl-runtime    # if available in extra/community

# GPU tooling for telemetry
pciutils                # lspci
python-pynvml           # via AUR at install-time, not ISO, see post-install hook
```

Rationale:

- `nvidia-dkms` ensures the NVIDIA kernel module is built against whatever kernel is shipped in the ISO; `nvidia-utils` and `opencl-nvidia` cover runtime and OpenCL without dragging in full CUDA.[^2][^3]
- ROCm full meta-packages (e.g., `rocm`, `hip-runtime-amd`) are several GB; instead, lean on the kernel’s `amdgpu` and optionally `rocm-opencl-runtime` if present, with a **Day 9.4** post-install script to pull heavier ROCm pieces only on AMD boxes.[^4][^5]

### 9.2 ArchISO Filesystem Overlay for GPU Utilities

In `archlive/airootfs/` ensure:

- `opt/yantra/core/hardware.py` is present and uses `pynvml` when `nvidia-smi` is installed, falls back to `rocm-smi`/`sysfs`/`lspci` for AMD/Intel, and surfaces a structured GPU capability to the Kriya Loop.[^1]
- `archlive/airootfs/etc/modprobe.d/yantra-nvidia.conf` (optional) can be used to blacklist nouveau if needed on older cards (but consider leaving nouveau enabled for compatibility unless you hit conflicts).

Example `hardware.py` snippet (conceptual wiring):

```python
# /opt/yantra/core/hardware.py (excerpt)
import subprocess

import pynvml

class GpuCapability(str):
    LOCAL_CAPABLE = "LOCAL_CAPABLE"
    CLOUD_ONLY = "CLOUD_ONLY"


def _detect_nvidia():
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        total_gb = mem_info.total / (1024 ** 3)
        return {
            "vendor": "NVIDIA",
            "vram_gb": round(total_gb, 1),
            "local_capable": total_gb >= 8,
        }
    except Exception:
        return None


def _detect_amd_intel():
    try:
        out = subprocess.check_output(["lspci", "-nn"], text=True)
        if "AMD" in out or "Radeon" in out:
            vendor = "AMD"
        elif "Intel" in out and "Graphics" in out:
            vendor = "INTEL"
        else:
            return None
        # Approx VRAM heuristic could be added via sysfs or drm-info here
        return {"vendor": vendor, "vram_gb": None, "local_capable": False}
    except Exception:
        return None


def detect_hardware_capability():
    nvidia = _detect_nvidia()
    if nvidia:
        return {
            **nvidia,
            "capability": GpuCapability.LOCAL_CAPABLE if nvidia["local_capable"] else GpuCapability.CLOUD_ONLY,
        }

    fallback = _detect_amd_intel()
    if fallback:
        return {**fallback, "capability": GpuCapability.CLOUD_ONLY}

    return {"vendor": "NONE", "vram_gb": 0, "capability": GpuCapability.CLOUD_ONLY}
```

This wires directly into the inference routing decision tree already described in §4.8 of your master context.[^1]

### 9.3 VRAM Binding for Local Inference

The Kriya Loop should use the capability object above to decide whether to start a local Ollama model versus cloud-only routing via LiteLLM.[^1]

Extend `core/hybrid_router.py` (or equivalent) to:

- Start Ollama with a CUDA/ROCm back-end only when `capability == LOCAL_CAPABLE`.
- Export VRAM telemetry to the Web HUD (`vram_usage.total_gb`, `vram_usage.used_gb`).[^1]

Example config fragment in `/opt/yantra/config.yaml`:

```yaml
inference:
  local:
    enabled: true
    model: "llama3.1:8b"
    endpoint: "http://127.0.0.1:11434"
    min_vram_gb: 8
  cloud:
    primary: "gemini/gemini-2.0-flash"
    fallback: "claude/claude-3.5-haiku"
```

The daemon bootstrap (`detect_hardware_capability`) should set an environment var such as `YANTRA_LOCAL_INFERENCE=1` when VRAM is sufficient, which the router reads to choose local vs. cloud paths.[^1]

### 9.4 Optional Post-Install GPU Enhancements

Ship a post-install hook in `/opt/yantra/deploy/install_gpu.sh` that runs **after** bare-metal installation (not during ISO live session) to offer optional full stacks:

```bash
#!/usr/bin/env bash
set -euo pipefail

GPU_VENDOR=$(lspci -nn | grep -E "VGA|3D" | grep -oE 'NVIDIA|AMD|Radeon' | head -n1 || true)

if [[ "$GPU_VENDOR" == "NVIDIA" ]]; then
  echo "[YANTRA] Detected NVIDIA GPU – optional CUDA install."
  read -rp "Install CUDA toolkit (2–5 GB)? [y/N] " REPLY
  if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    pacman --noconfirm -S --needed cuda cudnn
  fi
elif [[ "$GPU_VENDOR" == "AMD" || "$GPU_VENDOR" == "Radeon" ]]; then
  echo "[YANTRA] Detected AMD GPU – optional ROCm install."
  read -rp "Install ROCm runtime (2–5 GB)? [y/N] " REPLY
  if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    pacman --noconfirm -S --needed rocm-opencl-runtime
    # For full ROCm, instruct user or add distro-specific repo instructions
  fi
else
  echo "[YANTRA] No discrete GPU detected – skipping CUDA/ROCm extras."
fi
```

This keeps the ISO lean and pushes heavyweight dev stacks behind an explicit user choice.[^3][^2]

### 9.5 NetworkManager and Wi‑Fi Out-of-the-Box

Use **NetworkManager + iwd** as the unified networking layer instead of ad-hoc `iwctl` usage once installed.[^6][^7]

Add to `archlive/packages.x86_64`:

```text
# Networking
networkmanager
iwd

# Optional TUI frontends
nmtui            # ships in networkmanager

# DNS / resolver integration
systemd-resolvconf
```

In `archlive/airootfs/etc/systemd/system/multi-user.target.wants/` symlink:

```bash
ln -s /usr/lib/systemd/system/NetworkManager.service \
      archlive/airootfs/etc/systemd/system/multi-user.target.wants/NetworkManager.service

ln -s /usr/lib/systemd/system/iwd.service \
      archlive/airootfs/etc/systemd/system/multi-user.target.wants/iwd.service
```

Configure NetworkManager to use iwd as backend by shipping `/etc/NetworkManager/conf.d/wifi-backend.conf`:

```ini
# /etc/NetworkManager/conf.d/wifi-backend.conf
[device]
wifi.backend=iwd
```

This ensures Wi‑Fi works **in the live ISO** and persists into installed systems, with `nmcli`/`nmtui` as the unified interface.[^7][^6]

***

## Day 10 – Shell & UX: The Face of YantraOS

### 10.1 Kiosk Shell Strategy: Wayland vs. TUI

You want a non-root console that never exposes `root@archiso ~ #`. The options:

- A **Wayland kiosk shell** (Cage or Sway) that starts a fullscreen HUD/TUI app.
- A **pure TUI** (`textual`-based Yantra Shell) running on virtual console, with no graphical stack.[^1]

For v1.0 of a consumer OS, a **Wayland kiosk** booting directly into a Yantra dashboard aligns better with user expectations while still matching the geometric/matrix aesthetic.[^8][^9][^1]

### 10.2 Packages for Kiosk Shell

Extend `archlive/packages.x86_64`:

```text
# Wayland + kiosk compositor
sway
cage
alacritty          # terminal for fallback / debugging

# Fonts / theme for HUD
ttf-jetbrains-mono
inter-font

# Utilities
grim slurp wl-clipboard   # optional screenshot/clipboard tools
```

Rationale:

- `cage` runs a single maximized application; perfect for “HUD only” kiosk.[^9]
- `sway` is kept as a fallback multi-window compositor for dev/debug and potential future multi-pane HUD.[^8]

### 10.3 systemd User Session for Kiosk

Create a dedicated user (can be `yantra_user` distinct from `yantra_daemon`) and auto-login it on TTY1, then start Cage which launches your HUD (either a `textual` TUI in a terminal or a browser-based HUD pointing at yantraos.com).

`archlive/airootfs/etc/systemd/system/getty@tty1.service.d/override.conf`:

```ini
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin yantra_user --noclear %I 38400 linux
```

Then a user service for the kiosk shell:

```ini
# /home/yantra_user/.config/systemd/user/yantra-kiosk.service
[Unit]
Description=YantraOS Kiosk Shell
After=graphical-session-pre.target
Wants=graphical-session-pre.target

[Service]
Environment=MOZ_ENABLE_WAYLAND=1
Environment=QT_QPA_PLATFORM=wayland
ExecStart=/usr/bin/cage -s -- /usr/bin/alacritty -e /opt/yantra/venv/bin/python3 /opt/yantra/core/tui_shell.py
Restart=on-failure
RestartSec=2s

[Install]
WantedBy=default.target
```

During ISO build, place this at:

```text
archlive/airootfs/etc/skel/.config/systemd/user/yantra-kiosk.service
```

Then a user-level `systemd` preset:

```bash
sudo -u yantra_user systemctl --user enable yantra-kiosk.service
```

In the ISO overlay, approximate with a `chroot` in `compile_iso.sh` enabling user services for `yantra_user`.

### 10.4 Pure TUI Fallback (No Wayland)

Phase 2 of your architecture already defines Yantra Shell as a `textual` + `rich` TUI with three panes and a bottom prompt.[^1]

To boot directly into TUI on TTY1 (no graphical stack), create a different getty override in a “TUI build” profile:

```ini
# /etc/systemd/system/getty@tty1.service.d/override.conf
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin yantra_user --noclear %I 38400 linux
Type=simple

[Service]
ExecStartPost=/bin/sh -c 'exec /usr/bin/env YANTRA_TTY=1 /opt/yantra/venv/bin/python3 /opt/yantra/core/tui_shell.py'
```

The TUI uses the strict brand colors from `YANTRA_MASTER_CONTEXT.md` and reads from the IPC socket `/run/yantra/ipc.sock` to display Kriya Cycle phase, GPU telemetry, and ThoughtStream.[^1]

### 10.5 Matrix-Style HUD Wiring

The kiosk TUI (whether under Cage or raw TTY) should:

- Subscribe to the Kriya Loop’s IPC or WebSocket stream.
- Render the existing §2.7 “Terminal Boot Sequence” as the initial animation.[^1]
- Continuously poll the Kriya telemetry schema (`yantraos/telemetry/v1`) and map fields to your panes: GPUHealth, ThoughtStream, Telemetry Grid.[^1]

This leverages existing JSON schemas for telemetry and keeps UI logic cleanly separated from daemon logic.[^1]

***

## Day 11 – Security & Hardening: The Shield

### 11.1 Non-Root Daemon User and GPU Access

Your master context already defines `yantra_daemon` as a non-root user running the Kriya Loop under systemd with `ProtectSystem=strict` and constrained `ReadWritePaths`.[^1]

To align with the new `host_secrets.env` and GPU requirements while keeping security high:

- Ensure `yantra_daemon` is a member of the **`video` and `render` groups** to access `/dev/dri/*` and `/dev/nvidia*` devices on Arch.
- Keep it separate from `yantra_user` (kiosk shell) to avoid cross-privilege leakage.[^1]

`archlive/airootfs/etc/sysusers.d/yantra.conf`:

```ini
# /etc/sysusers.d/yantra.conf
u yantra_daemon - "YantraOS Daemon" /opt/yantra
m yantra_daemon video
m yantra_daemon render

u yantra_user   - "YantraOS Shell"  /home/yantra_user
m yantra_user video
m yantra_user render
```

`archlive/airootfs/etc/tmpfiles.d/yantra.conf`:

```ini
# /etc/tmpfiles.d/yantra.conf
d /run/yantra 0750 yantra_daemon yantra -
d /var/lib/yantra 0750 yantra_daemon yantra -
d /var/log/yantra 0750 yantra_daemon yantra -
```

### 11.2 Updated `yantra.service` Hardening

Update the service to reference `host_secrets.env` and fine-tune security directives:[^10][^11][^1]

```ini
# /etc/systemd/system/yantra.service
[Unit]
Description=YantraOS Kriya Loop Daemon — Autonomous System Orchestrator
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/run/yantra /var/lib/yantra

[Service]
Type=notify
User=yantra_daemon
Group=yantra

WorkingDirectory=/opt/yantra
ExecStart=/opt/yantra/venv/bin/python3 /opt/yantra/core/daemon.py
Environment=PYTHONPATH=/opt/yantra
EnvironmentFile=-/etc/yantra/host_secrets.env

Restart=on-failure
RestartSec=5s
WatchdogSec=30s
WatchdogSignal=SIGABRT
NotifyAccess=main

# Hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
PrivateTmp=yes
PrivateDevices=no          # must be NO to allow GPU devices via groups
MemoryDenyWriteExecute=no  # JIT-heavy ML libs need executable memory
UMask=0077

# Limit write scope
ReadWritePaths=/run/yantra /var/lib/yantra /var/log/yantra

# Capability bounding: no extra caps needed if using group-based GPU access
CapabilityBoundingSet=
AmbientCapabilities=

[Install]
WantedBy=multi-user.target
```

Notes:

- `PrivateDevices=no` is required to see `/dev/dri/*` and `/dev/nvidia*`; the risk is mitigated by group-based access and lack of elevated capabilities.[^10]
- `UMask=0077` ensures any new files (including telemetry cache) are not world-readable.[^11][^10]

### 11.3 Secrets File Permissions

`archlive/compile_iso.sh` already stages `/etc/yantra/host_secrets.env` with `0400/0600` permissions per your latest context.[^1]

Ensure the final ISO overlay contains:

```bash
install -Dm600 host_secrets.env "${airootfs_dir}/etc/yantra/host_secrets.env"
```

and that at runtime:

```bash
chown root:yantra /etc/yantra/host_secrets.env
chmod 0640 /etc/yantra/host_secrets.env
```

With `User=yantra_daemon` and `Group=yantra`, the daemon can read secrets while no other non-yantra users can.[^1]

### 11.4 UFW Firewall Baseline

Ship `ufw` as a simple, user-friendly firewall frontend and default to **deny inbound, allow outbound**, with only SSH optionally open.

Add to `archlive/packages.x86_64`:

```text
ufw
```

`archlive/airootfs/etc/ufw/ufw.conf`:

```ini
# /etc/ufw/ufw.conf
ENABLED=yes
IPV6=yes
DEFAULT_INPUT_POLICY="DROP"
DEFAULT_OUTPUT_POLICY="ACCEPT"
DEFAULT_FORWARD_POLICY="DROP"
```

Additional rules (shipped in `/etc/ufw/applications.d/yantra` or a one-shot script):

```bash
ufw default deny incoming
ufw default allow outgoing

# Optional: allow SSH for remote admin
ufw allow 22/tcp

# YantraOS daemon only talks outbound (telemetry, cloud LLMs) – no inbound ports required
ufw enable
```

Enable UFW at install:

```bash
systemctl enable --now ufw.service
```

Given Kriya Loop does only outbound HTTP(S) and local IPC, no inbound exceptions are needed for core functionality.[^1]

***

## Day 12 – First-Boot Experience & Onboarding

### 12.1 ArchISO First-Boot Hook: `/root/.automated_script.sh`

ArchISO supports a special `/root/.automated_script.sh` that runs automatically at login (and can be configured to run once) on the live environment.[^1]

Design the script to:

1. Ask the user to connect to Wi‑Fi using `nmtui` or `nmcli` (with NetworkManager + iwd already active).[^12][^6][^7]
2. Ping the Vercel HUD (`https://yantraos.com/api/health`) to verify connectivity.[^1]
3. Start/enable `yantra.service` and confirm the Kriya Loop is `ACTIVE` via systemd journal output.

Example `archlive/airootfs/root/.automated_script.sh`:

```bash
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

# 2) Prompt user to configure Wi‑Fi
if ! ping -c1 -W2 yantraos.com >/dev/null 2>&1; then
  echo "[YANTRA] Network not detected. Launching nmtui for Wi‑Fi setup..."
  sleep 1
  nmtui
fi

# Re-test connectivity
if ping -c1 -W5 yantraos.com >/dev/null 2>&1; then
  echo "[YANTRA] Network OK – contacting Yantra HUD health endpoint..."
  curl -fsSL https://yantraos.com/api/health || echo "[WARN] HUD health check failed"
else
  echo "[ERROR] Network still unavailable. Kriya Loop will run in offline mode."
fi

# 3) Enable and start Kriya Loop
if ! systemctl is-enabled --quiet yantra.service; then
  echo "[YANTRA] Enabling yantra.service..."
  systemctl enable yantra.service
fi

echo "[YANTRA] Starting Kriya Loop daemon..."
systemctl start yantra.service

sleep 2
systemctl --no-pager --full status yantra.service || true

# Optional: hand over to TUI shell on TTY1
if command -v chvt >/dev/null 2>&1; then
  chvt 1 || true
fi

# Disable self on next boot (live session only)
rm -f /root/.automated_script.sh
```

This script ensures:

- Wi‑Fi is configured via NetworkManager.
- Vercel HUD connectivity is sanity-checked.
- `yantra.service` is enabled and started, with logs visible to the user.

### 12.2 Installed System First-Boot

For installed systems (post-`install.sh`), create a systemd unit that triggers an onboarding script once.

`/etc/systemd/system/yantra-onboarding.service`:

```ini
[Unit]
Description=YantraOS First-Boot Onboarding
After=network-online.target
Wants=network-online.target
ConditionFirstBoot=yes

[Service]
Type=oneshot
ExecStart=/opt/yantra/deploy/onboarding.sh
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
```

`/opt/yantra/deploy/onboarding.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Ensure networking
if ! systemctl is-active --quiet NetworkManager; then
  systemctl start NetworkManager
fi

# Prompt Wi‑Fi if offline
if ! ping -c1 -W3 yantraos.com >/dev/null 2>&1; then
  echo "[YANTRA] No network detected. Launching nmtui..."
  nmtui || true
fi

# Telemetry check
curl -fsSL https://yantraos.com/api/health || echo "[WARN] HUD health check failed"

# Enable + start Kriya Loop
systemctl enable --now yantra.service

# Optionally start the kiosk shell or TUI
loginctl enable-linger yantra_user || true
sudo -u yantra_user systemctl --user enable --now yantra-kiosk.service || true
```

This mirrors the live ISO onboarding but uses `ConditionFirstBoot=yes` to restrict it to the first boot only.[^7]

***

## Days 13–14 – QA, Edge Cases, Distribution & Launch

### 13.1 Hardware Matrix & Edge-Case Testing

Construct a minimal test matrix:

- NVIDIA desktop with ≥ 8 GB VRAM (e.g., RTX 3060/3070) – validate `LOCAL_CAPABLE` routing, Ollama local inference, VRAM telemetry in HUD.[^1]
- AMD Radeon desktop/mobile – ensure system boots with `amdgpu`, no black screen, HUD functional, falls back to `CLOUD_ONLY` routing.
- Intel iGPU laptop – verify fallbacks and low-VRAM behavior (cloud-only inference, no crash in `pynvml`).[^1]
- No GPU / VM (QEMU) – ensure VRAM mock path is disabled and new detection code reports vendor `NONE`, Kriya Loop uses cloud-only path.[^1]

For each, run:

```bash
systemctl status yantra.service
journalctl -u yantra.service -b --output=cat

lsmod | grep -E 'nvidia|amdgpu|i915'

python -m pip show pynvml || echo "pynvml missing"
```

And confirm:

- `detect_hardware_capability()` does not raise.[^1]
- Telemetry payload shows correct `vram_usage.total_gb` and `inference_routing` fields in the Web HUD.[^1]

### 13.2 ArchISO Boot Paths

Test boot on:

- BIOS + legacy boot.
- UEFI with and without Secure Boot (if supported).
- USB vs. virtual CD in QEMU.

Confirm:

- `/root/.automated_script.sh` runs only once and then deletes itself.
- Kiosk shell starts automatically for `yantra_user`.
- `yantra.service` is active and watchdog heartbeats function (simulate deadlock to see restart).[^13]

### 13.3 ISO Build and Verification

Ensure `compile_iso.sh` enforces the six invariants from your master context and additionally validates GPU and onboarding assets.[^1]

Add post-build checks:

```bash
ISO=yantraos-x86_64.iso

# 1) Verify pacman database and keyring
archlint "$ISO" || echo "[WARN] archlint missing or failed"

# 2) List kernel + GPU packages
bsdtar -tf "$ISO" | grep -E 'nvidia|amdgpu|mesa' || true

# 3) Confirm presence of onboarding + services
bsdtar -tf "$ISO" | grep -E 'yantra.service|yantra-onboarding.service|automated_script.sh'
```

Generate checksums and optional GPG signature for distribution:

```bash
sha256sum "$ISO" > "$ISO.sha256"
# gpg --sign --armor --detach-sign "$ISO"
```

### 13.4 ISO Distribution Strategy

Given legal/copyright constraints of NVIDIA CUDA and ROCm, keep distribution focused on:

- ISO that includes **runtime drivers** (`nvidia-dkms`, `nvidia-utils`, `rocm-opencl-runtime`) from official Arch repos.[^2][^3]
- Post-install script for optional full CUDA/ROCm stacks (user-initiated download from Arch repos, not redistributed by you).[^3][^2]

Distribution channels:

- GitHub Releases in the `osyantra` org with:
  - ISO file.
  - `.sha256` checksum.
  - Optional `.sig` detached signature.
  - `CHANGELOG.md` entry summarizing Day 9–14 features.

### 13.5 Open-Source Launch Checklist

Repository layout:

- `osyantra/yantraos-archiso` (public):
  - `archlive/` profile (packages, airootfs overlay, systemd units).
  - `compile_iso.sh` and `build.sh` scripts.
  - `LICENSE` (e.g., GPL-3.0-or-later for scripts, CC-BY-SA or dual-license for docs).

Launch checklist:

- [ ] Ensure secrets are never committed (all `.env` and `host_secrets.env` in `.gitignore`).[^1]
- [ ] Document hardware requirements (recommended ≥ 8 GB VRAM for local inference; cloud-only works on any x86_64 with 8 GB RAM).[^1]
- [ ] Provide quickstart:
  - Flash ISO with `dd`/`balenaEtcher`.
  - Boot, connect Wi‑Fi, watch Kriya Loop spin up.
  - Visit `https://yantraos.com` to see telemetry in real time.[^1]
- [ ] Add CONTRIBUTING.md with guidelines for:
  - New hardware support (ARM, multi-GPU, laptops).
  - New Skills and telemetry fields.
  - Security disclosures for sandbox or daemon.

With these six days, YantraOS moves from a backend-complete prototype to a GPU-aware, kiosk-presented, hardened, and testable consumer OS image aligned tightly with the architecture already codified in `YANTRA_MASTER_CONTEXT.md`.[^1]

---

## References

1. [YANTRA_MASTER_CONTEXT.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/84033475/c1f9c612-6061-4e28-9e8e-54b144ded22b/YANTRA_MASTER_CONTEXT.md?AWSAccessKeyId=<AWS_ACCESS_KEY_REDACTED>&Signature=ZNv%2FV8mjVQiHq6xsRkAv%2B%2F1y348%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEJD%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJIMEYCIQCZCbPrB7Jc0wKzpKUNoU0U4WHPCG2OAQlP%2BpL5bXLocQIhAIujzuGPIm%2F%2FXFaz08CNVDVI%2FPvfXsHQFKkwA9NrfaqCKvMECFkQARoMNjk5NzUzMzA5NzA1Igz5zznYN9YSVwj2sYAq0ATIWqKHlq5MocAr3q7YCD2yam9ehC4odzdlkk93Kw1x37iN3XCeuRQrVS7QVez%2Bx0jantY%2FKbBn1Ba%2Felrwgz60K69oBaKAszXoyyxzlLEpq95ZKNFZy0iAyHyzS4%2BN4vnZi6IBmmpTK3QK1ZtHqiI6tInuot4SrKPquhXBHggQ7%2BuBx6fV0rRKiDxspWflFtQKhaM%2B5MP7EVBy35LXSBq%2FAIUIyIS7QpEY90J6PTdnv7YMx4c%2BPCp08eeZmgMjaflJUpsMHqG4atyNMKopHpWeWSGirGrYQY08N9bgJWIdjbsfjstfnvAfSPMrfNjBFhZX%2FIpv8NF6eW1CoBiPYrWLB4S5TozqkwAeHrLz%2BX6B4Ltc705b2s3iNuNLKpJ3HxGpXs5PH%2BbxFJGOg3MU%2BLSJcobfPqG0F2PtRJGXaYNpmTc6SbXd3qO8yVhaYoUiE15kMmR2Wat4pzbybpHKqbBt7kKje%2BSFtdMZM7kz8O2MfNOM0ylJKoiZZN5Qtngq9TW6BVHod3cDt19o3kVK0GDb7O%2FR1pW%2BT%2FwaQQXXyCb%2BHxVA7U5zC2WKKs%2FH0rbDTCDGEsmgF6QZV6EgqU%2BO34Js6j43UQ57zVyfohK5kwO7tInN7OITk3hVemzsBDjTV0A3RaGZZJfwqaxU6Nh1uYZa1vHNSKbLLpeI2xkFqZO2eImau%2BlCq3QJWdjTtaUsdbxMSZnhDfdY4%2FLp8bcyU856FuadTw%2BFXEtb4XoZG5Cjk8ZHbL7weogEsZPqsR7Qnn9Hff7zydND0kwYccLJYmbqMLGZjM0GOpcBsCIIh%2BUNEk3Tnfy06keVnHnfVorrs5TGjvVzy27sKkVGH%2F8Oj856n%2FOUBdauJfTy%2FEuE2uA4vYSm67II7ZDpwaQ9AdSNN0wqrKUv5%2ByJeMW%2BmW8DaXjDMXv%2B23Jy0h3aCuXuaoi2QQr2qlXCDyk47c1C0fNXdQideJQ5cdzu15FJw4lA6pG4p%2BgW2pHt6ltOnksPO2VU7A%3D%3D&Expires=1772297429) - # YANTRA_MASTER_CONTEXT.md — Unified Engine Memory

> **Version:** 3.1.0 | **Generated:** 2026-02-...

2. [cuda 13.1.1-1 (x86_64) - Arch Linux](https://archlinux.org/packages/extra/x86_64/cuda/) - NVIDIA's GPU programming toolkit. Upstream URL: https://developer.nvidia.com/cuda-zone. License(s):,...

3. [cuda 12.9.1-2 (x86_64) - Arch Linux](http://www.archlinux.jp/packages/extra/x86_64/cuda/)

4. [rocm opencl runtime package is quite large.](https://bbs.archlinux.org/viewtopic.php?id=306750)

5. [Install Package Manager — Use ROCm on Radeon and Ryzen](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installryz/native_linux/install-package-manager.html) - To use pre-built ROCm libraries and tools, include ROCm runtime packages in the installation step. T...

6. [iwd - ArchWiki](https://wiki.archlinux.org/title/Iwd) - iwd (iNet wireless daemon) is a wireless daemon for Linux written by Intel. The core goal of the pro...

7. [NetworkManager - ArchWiki](https://wiki.archlinux.org/title/NetworkManager) - NetworkManager is a program for providing detection and configuration for systems to automatically c...

8. [linux-kiosk-mode/sway/config at main · zerodays/linux-kiosk-mode](https://github.com/zerodays/linux-kiosk-mode/blob/main/sway/config) - Kiosk mode configuration and instructions using Sway and Plymouth. - zerodays/linux-kiosk-mode

9. [cage-kiosk/cage: A Wayland kiosk](https://github.com/cage-kiosk/cage) - This is Cage, a Wayland kiosk. A kiosk runs a single, maximized application. This README is only rel...

10. [Systemd Units Hardening](https://docs.rockylinux.org/10/guides/security/systemd_hardening/) - This basically means that capabilities can grant some of root privileges to unprivileged processes b...

11. [Systemd Units Hardening - Rocky Linux Documentationdocs.rockylinux.org › guides › security › systemd_hardening](https://docs.rockylinux.org/9/guides/security/systemd_hardening/)

12. [Shell - network in arch linux](https://www.dekgenius.com/script-code-example/shell_example_network-in-arch-linux.html?t=csharp) - code example for shell - network in arch linux - Best free resources for learning to code and The we...

13. [System-Context_-You-are-the-Systemd-Integration-Sp-1.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/84033475/85c1ea56-338a-403a-b7d9-3e19bac3f84f/System-Context_-You-are-the-Systemd-Integration-Sp-1.md?AWSAccessKeyId=<AWS_ACCESS_KEY_REDACTED>&Signature=VSOR3eCBigeqALNAZUkzV6U%2BD%2BE%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEJD%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJIMEYCIQCZCbPrB7Jc0wKzpKUNoU0U4WHPCG2OAQlP%2BpL5bXLocQIhAIujzuGPIm%2F%2FXFaz08CNVDVI%2FPvfXsHQFKkwA9NrfaqCKvMECFkQARoMNjk5NzUzMzA5NzA1Igz5zznYN9YSVwj2sYAq0ATIWqKHlq5MocAr3q7YCD2yam9ehC4odzdlkk93Kw1x37iN3XCeuRQrVS7QVez%2Bx0jantY%2FKbBn1Ba%2Felrwgz60K69oBaKAszXoyyxzlLEpq95ZKNFZy0iAyHyzS4%2BN4vnZi6IBmmpTK3QK1ZtHqiI6tInuot4SrKPquhXBHggQ7%2BuBx6fV0rRKiDxspWflFtQKhaM%2B5MP7EVBy35LXSBq%2FAIUIyIS7QpEY90J6PTdnv7YMx4c%2BPCp08eeZmgMjaflJUpsMHqG4atyNMKopHpWeWSGirGrYQY08N9bgJWIdjbsfjstfnvAfSPMrfNjBFhZX%2FIpv8NF6eW1CoBiPYrWLB4S5TozqkwAeHrLz%2BX6B4Ltc705b2s3iNuNLKpJ3HxGpXs5PH%2BbxFJGOg3MU%2BLSJcobfPqG0F2PtRJGXaYNpmTc6SbXd3qO8yVhaYoUiE15kMmR2Wat4pzbybpHKqbBt7kKje%2BSFtdMZM7kz8O2MfNOM0ylJKoiZZN5Qtngq9TW6BVHod3cDt19o3kVK0GDb7O%2FR1pW%2BT%2FwaQQXXyCb%2BHxVA7U5zC2WKKs%2FH0rbDTCDGEsmgF6QZV6EgqU%2BO34Js6j43UQ57zVyfohK5kwO7tInN7OITk3hVemzsBDjTV0A3RaGZZJfwqaxU6Nh1uYZa1vHNSKbLLpeI2xkFqZO2eImau%2BlCq3QJWdjTtaUsdbxMSZnhDfdY4%2FLp8bcyU856FuadTw%2BFXEtb4XoZG5Cjk8ZHbL7weogEsZPqsR7Qnn9Hff7zydND0kwYccLJYmbqMLGZjM0GOpcBsCIIh%2BUNEk3Tnfy06keVnHnfVorrs5TGjvVzy27sKkVGH%2F8Oj856n%2FOUBdauJfTy%2FEuE2uA4vYSm67II7ZDpwaQ9AdSNN0wqrKUv5%2ByJeMW%2BmW8DaXjDMXv%2B23Jy0h3aCuXuaoi2QQr2qlXCDyk47c1C0fNXdQideJQ5cdzu15FJw4lA6pG4p%2BgW2pHt6ltOnksPO2VU7A%3D%3D&Expires=1772297429) - <img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margi...

