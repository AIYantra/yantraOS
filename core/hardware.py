"""
YantraOS — Hardware Telemetry Probe (Cross-Platform)
Target: /opt/yantra/core/hardware.py
Phase 2 Alpha

Abstracts GPU / CPU / disk telemetry collection.
On Linux with NVIDIA GPUs: uses pynvml for real hardware data.
Fallback: uses subprocess.check_output(["lspci", "-nn"]) for AMD/Intel detection.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Tuple

log = logging.getLogger("yantra.hardware")


# ── Telemetry Snapshots ───────────────────────────────────────────────────────


@dataclass
class GPUState:
    """Snapshot of a single GPU's telemetry."""
    name: str = "Unknown GPU"
    vram_used_gb: float = 0.0
    vram_total_gb: float = 0.0
    gpu_util_pct: float = 0.0
    temp_c: int = 0
    power_w: float = 0.0
    vendor: str = "unknown"     # "nvidia", "amd", "intel", "unknown"


# ── NVIDIA Probe (pynvml) ────────────────────────────────────────────────────


def _probe_nvidia() -> GPUState | None:
    """
    Attempt to read real GPU telemetry via pynvml.
    Returns a GPUState on success, None if pynvml is unavailable or fails.
    """
    try:
        import pynvml  # type: ignore[import-not-found]

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW → W

        vram_total_gb = mem.total / (1024 ** 3)
        vram_used_gb = mem.used / (1024 ** 3)

        state = GPUState(
            name=name,
            vram_used_gb=vram_used_gb,
            vram_total_gb=vram_total_gb,
            gpu_util_pct=float(util.gpu),
            temp_c=temp,
            power_w=power,
            vendor="nvidia",
        )
        log.info(
            f"> HARDWARE: {state.name} — "
            f"VRAM {state.vram_used_gb:.1f}/{state.vram_total_gb:.1f}GB — "
            f"GPU {state.gpu_util_pct:.0f}% — {state.temp_c}°C"
        )
        return state

    except Exception as e:
        log.warning(f"> HARDWARE: pynvml probe failed: {e}")
        return None


# ── sysfs VRAM Probe (AMD/Intel) ──────────────────────────────────────────────


def _probe_sysfs_vram() -> float:
    """
    Read real VRAM from sysfs for AMD GPUs.

    Path: /sys/class/drm/card*/device/mem_info_vram_total
    Returns VRAM in GB, or 0.0 if the sysfs node doesn't exist
    (Intel iGPUs, older kernels, or non-AMD hardware).
    """
    import glob

    for card_path in sorted(glob.glob("/sys/class/drm/card*/device/mem_info_vram_total")):
        try:
            with open(card_path, "r") as f:
                vram_bytes = int(f.read().strip())
            vram_gb = vram_bytes / (1024 ** 3)
            if vram_gb > 0:
                log.info(f"> HARDWARE: sysfs VRAM detected via {card_path}: {vram_gb:.1f} GB")
                return vram_gb
        except (ValueError, OSError, IOError) as e:
            log.debug(f"> HARDWARE: sysfs probe failed for {card_path}: {e}")
            continue

    return 0.0


# ── lspci Fallback (AMD/Intel) ────────────────────────────────────────────────


def _probe_lspci() -> GPUState:
    """
    Fallback GPU detection using lspci -nn.
    Identifies AMD/Intel discrete or integrated GPUs.

    GATE 4 FIX: AMD VRAM is no longer hardcoded. We probe sysfs
    (/sys/class/drm/card*/device/mem_info_vram_total) for real values.
    APUs may report 0 or a small dedicated VRAM allocation.
    """
    try:
        raw = subprocess.check_output(
            ["lspci", "-nn"],
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        log.warning(f"> HARDWARE: lspci probe failed: {e}")
        return GPUState(
            name="No GPU Detected",
            vendor="unknown",
        )

    # Parse lspci output for VGA/3D controllers
    gpu_name = "Unknown GPU"
    vendor = "unknown"

    for line in raw.splitlines():
        lower = line.lower()
        if "vga" not in lower and "3d" not in lower and "display" not in lower:
            continue

        # Identify vendor
        if "nvidia" in lower:
            vendor = "nvidia"
            gpu_name = line.split(":")[-1].strip()
            # NVIDIA detected via lspci but pynvml failed — likely no driver
            log.info(f"> HARDWARE: NVIDIA GPU found via lspci (no driver): {gpu_name}")
            return GPUState(
                name=gpu_name,
                vendor="nvidia",
            )
        elif "advanced micro" in lower or "amd" in lower or "ati" in lower:
            vendor = "amd"
            gpu_name = line.split(":")[-1].strip()

            # ── GATE 4: Deterministic AMD VRAM via sysfs ──────────────
            # DO NOT guess VRAM from lspci product names. Read the real
            # value from /sys/class/drm/card*/device/mem_info_vram_total.
            sysfs_vram = _probe_sysfs_vram()
            vram_msg = f"{sysfs_vram:.1f} GB" if sysfs_vram > 0 else "not reported"
            log.info(
                f"> HARDWARE: AMD GPU detected: {gpu_name} — "
                f"sysfs VRAM: {vram_msg}"
            )
            return GPUState(
                name=gpu_name,
                vram_total_gb=sysfs_vram,
                vendor="amd",
            )
        elif "intel" in lower:
            vendor = "intel"
            gpu_name = line.split(":")[-1].strip()
            log.info(f"> HARDWARE: Intel integrated GPU detected: {gpu_name}")
            return GPUState(
                name=gpu_name,
                vendor="intel",
            )

    log.warning("> HARDWARE: No recognized GPU found via lspci.")
    return GPUState(
        name=gpu_name,
        vendor=vendor,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def probe_gpu() -> GPUState:
    """
    Probe GPU hardware telemetry.

    Strategy:
      1. Attempt pynvml (NVIDIA with driver) for real telemetry.
      2. Fallback to lspci -nn (AMD/Intel/driverless NVIDIA).
    """
    # Primary: pynvml for NVIDIA with working drivers
    nvidia_state = _probe_nvidia()
    if nvidia_state is not None:
        return nvidia_state

    # Fallback: lspci for AMD/Intel/driverless
    return _probe_lspci()


def probe_cpu_disk() -> Tuple[float, float, float]:
    """
    Return (cpu_percent, disk_free_gb, ram_percent).
    On Windows: uses C:\\ as the disk root.
    On Linux: uses /opt/yantra if it exists, otherwise /.
    """
    cpu_pct = 0.0
    disk_free_gb = 0.0
    ram_pct = 0.0

    try:
        import psutil  # type: ignore[import-not-found]

        cpu_pct = psutil.cpu_percent(interval=0.5)
        ram_pct = psutil.virtual_memory().percent

        if os.name == "nt":
            disk_path = "C:\\"
        else:
            disk_path = "/tmp"  # ALway explicit check /tmp (writable overlay) to fix TUI reporting 0.0 GB on Live USB

        disk_free_gb = psutil.disk_usage(disk_path).free / (1024 ** 3)

    except Exception as e:
        log.warning(f"> HARDWARE: CPU/Disk probe failed: {e}")

    return cpu_pct, disk_free_gb, ram_pct


_auth_log_position: int = 0
_auth_log_initialized: bool = False

async def get_ssh_telemetry() -> str:
    """Extract SSH auth logs for anomaly detection."""
    global _auth_log_position
    global _auth_log_initialized
    log_path = "/host_log/auth.log"
    try:
        if not os.path.exists(log_path):
            return ""
            
        file_size = os.path.getsize(log_path)
        
        if not _auth_log_initialized:
            # First run: start from the end to avoid blowing up Azure TPM rate limits
            _auth_log_position = max(0, file_size - 10000)
            _auth_log_initialized = True

        if file_size < _auth_log_position:
            _auth_log_position = 0
            
        with open(log_path, "rb") as f:
            f.seek(_auth_log_position)
            data = f.read()
            _auth_log_position = f.tell()
            
        raw = data.decode("utf-8", errors="replace").replace("\x00", "")
        # Expand clamp to 500k chars (~125k tokens) to safely fit within the 272k limit
        return raw[-500000:].strip()
    except Exception as e:
        log.warning(f"> HARDWARE: SSH telemetry probe failed: {e}")
        return ""
