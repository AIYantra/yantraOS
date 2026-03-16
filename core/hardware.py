"""
YantraOS — Hardware Telemetry Probe (Cross-Platform)
Target: /opt/yantra/core/hardware.py
Phase 2 Alpha

Abstracts GPU / CPU / disk telemetry collection.
On Linux with NVIDIA GPUs: uses pynvml for real hardware data.
Fallback: uses subprocess.check_output(["lspci", "-nn"]) for AMD/Intel detection.
Returns a strict capability state:
  GpuCapability.LOCAL_CAPABLE (≥ 8GB VRAM)
  GpuCapability.CLOUD_ONLY   (< 8GB VRAM or no discrete GPU)
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Tuple

log = logging.getLogger("yantra.hardware")


# ── Capability Classification ─────────────────────────────────────────────────

# Minimum VRAM threshold (GB) for local inference eligibility.
VRAM_LOCAL_THRESHOLD_GB: float = 8.0


class GpuCapability(str, Enum):
    """Strict capability tier returned by the hardware probe."""
    LOCAL_CAPABLE = "LOCAL_CAPABLE"   # ≥ 8GB VRAM — full local inference
    CLOUD_ONLY = "CLOUD_ONLY"        # < 8GB VRAM or no discrete GPU


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
    capability: GpuCapability = GpuCapability.CLOUD_ONLY
    vendor: str = "unknown"     # "nvidia", "amd", "intel", "unknown"


@dataclass
class HardwareSnapshot:
    """Full hardware telemetry snapshot."""
    gpu: GPUState
    cpu_pct: float = 0.0
    disk_free_gb: float = 0.0


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

        # Strict capability classification based on total VRAM
        capability = (
            GpuCapability.LOCAL_CAPABLE
            if vram_total_gb >= VRAM_LOCAL_THRESHOLD_GB
            else GpuCapability.CLOUD_ONLY
        )

        state = GPUState(
            name=name,
            vram_used_gb=vram_used_gb,
            vram_total_gb=vram_total_gb,
            gpu_util_pct=float(util.gpu),
            temp_c=temp,
            power_w=power,
            capability=capability,
            vendor="nvidia",
        )
        log.info(
            f"> HARDWARE: {state.name} — "
            f"VRAM {state.vram_used_gb:.1f}/{state.vram_total_gb:.1f}GB — "
            f"GPU {state.gpu_util_pct:.0f}% — {state.temp_c}°C — "
            f"Capability: {state.capability.value}"
        )
        return state

    except Exception as e:
        log.warning(f"> HARDWARE: pynvml probe failed: {e}")
        return None


# ── lspci Fallback (AMD/Intel) ────────────────────────────────────────────────


def _probe_lspci() -> GPUState:
    """
    Fallback GPU detection using lspci -nn.
    Identifies AMD/Intel discrete or integrated GPUs.
    Since lspci cannot report VRAM, we classify as CLOUD_ONLY
    unless an AMD discrete GPU (Radeon RX) is detected.
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
            capability=GpuCapability.CLOUD_ONLY,
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
                capability=GpuCapability.CLOUD_ONLY,
                vendor="nvidia",
            )
        elif "advanced micro" in lower or "amd" in lower or "ati" in lower:
            vendor = "amd"
            gpu_name = line.split(":")[-1].strip()
            # Check if it's a discrete Radeon RX card (likely ≥ 8GB)
            if "radeon rx" in lower or "navi" in lower or "vega" in lower:
                log.info(f"> HARDWARE: AMD discrete GPU detected: {gpu_name}")
                return GPUState(
                    name=gpu_name,
                    vram_total_gb=8.0,  # Conservative estimate for discrete AMD
                    capability=GpuCapability.LOCAL_CAPABLE,
                    vendor="amd",
                )
            else:
                log.info(f"> HARDWARE: AMD integrated GPU detected: {gpu_name}")
                return GPUState(
                    name=gpu_name,
                    capability=GpuCapability.CLOUD_ONLY,
                    vendor="amd",
                )
        elif "intel" in lower:
            vendor = "intel"
            gpu_name = line.split(":")[-1].strip()
            log.info(f"> HARDWARE: Intel integrated GPU detected: {gpu_name}")
            return GPUState(
                name=gpu_name,
                capability=GpuCapability.CLOUD_ONLY,
                vendor="intel",
            )

    log.warning("> HARDWARE: No recognized GPU found via lspci.")
    return GPUState(
        name=gpu_name,
        capability=GpuCapability.CLOUD_ONLY,
        vendor=vendor,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def probe_gpu() -> GPUState:
    """
    Probe GPU hardware with strict capability classification.

    Strategy:
      1. Attempt pynvml (NVIDIA with driver) — get real VRAM and classify.
      2. Fallback to lspci -nn (AMD/Intel/driverless NVIDIA) — heuristic classify.

    Returns:
        GPUState with capability set to LOCAL_CAPABLE or CLOUD_ONLY.
    """
    # Primary: pynvml for NVIDIA with working drivers
    nvidia_state = _probe_nvidia()
    if nvidia_state is not None:
        return nvidia_state

    # Fallback: lspci for AMD/Intel/driverless
    return _probe_lspci()


def probe_cpu_disk() -> Tuple[float, float]:
    """
    Return (cpu_percent, disk_free_gb).
    On Windows: uses C:\\ as the disk root.
    On Linux: uses /opt/yantra if it exists, otherwise /.
    """
    cpu_pct = 0.0
    disk_free_gb = 0.0

    try:
        import psutil  # type: ignore[import-not-found]

        cpu_pct = psutil.cpu_percent(interval=0.5)

        if os.name == "nt":
            disk_path = "C:\\"
        else:
            disk_path = "/tmp"  # ALway explicit check /tmp (writable overlay) to fix TUI reporting 0.0 GB on Live USB

        disk_free_gb = psutil.disk_usage(disk_path).free / (1024 ** 3)

    except Exception as e:
        log.warning(f"> HARDWARE: CPU/Disk probe failed: {e}")

    return cpu_pct, disk_free_gb


def probe_all() -> HardwareSnapshot:
    """Collect a full hardware snapshot."""
    gpu = probe_gpu()
    cpu_pct, disk_free_gb = probe_cpu_disk()
    return HardwareSnapshot(gpu=gpu, cpu_pct=cpu_pct, disk_free_gb=disk_free_gb)
