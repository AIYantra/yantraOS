"""
YantraOS — Hardware Telemetry Probe (Cross-Platform)
Model Route: Gemini 3.1 Pro (High)

Abstracts GPU / CPU / disk telemetry collection.
On Linux with NVIDIA GPUs: uses pynvml for real hardware data.
On Windows or without CUDA: returns mock LOCAL_CAPABLE state.
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass

log = logging.getLogger("yantra.hardware")


@dataclass
class GPUState:
    """Snapshot of a single GPU's telemetry."""
    name: str = "Unknown GPU"
    vram_used_gb: float = 0.0
    vram_total_gb: float = 16.0
    gpu_util_pct: float = 0.0
    temp_c: int = 0
    power_w: float = 0.0
    local_capable: bool = True


@dataclass
class HardwareSnapshot:
    """Full hardware telemetry snapshot."""
    gpu: GPUState
    cpu_pct: float = 0.0
    disk_free_gb: float = 0.0


def _mock_gpu() -> GPUState:
    """Return a mock GPU state for testing on Windows / non-CUDA systems."""
    log.info("> HARDWARE: Using mock GPU state (LOCAL_CAPABLE=True, 16GB VRAM)")
    return GPUState(
        name="Mock NVIDIA RTX 4090 (Simulated)",
        vram_used_gb=4.2,
        vram_total_gb=16.0,
        gpu_util_pct=12.0,
        temp_c=42,
        power_w=85.0,
        local_capable=True,
    )


def probe_gpu() -> GPUState:
    """
    Attempt to read real GPU telemetry via pynvml.
    Falls back to mock data on any failure.
    """
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW → W

        state = GPUState(
            name=name,
            vram_used_gb=mem.used / (1024 ** 3),
            vram_total_gb=mem.total / (1024 ** 3),
            gpu_util_pct=float(util.gpu),
            temp_c=temp,
            power_w=power,
            local_capable=True,
        )
        log.info(
            f"> HARDWARE: {state.name} — "
            f"VRAM {state.vram_used_gb:.1f}/{state.vram_total_gb:.1f}GB — "
            f"GPU {state.gpu_util_pct:.0f}% — {state.temp_c}°C"
        )
        return state

    except Exception as e:
        log.warning(f"> HARDWARE: pynvml probe failed: {e}. Falling back to mock.")
        return _mock_gpu()


def probe_cpu_disk() -> tuple[float, float]:
    """
    Return (cpu_percent, disk_free_gb).
    On Windows: uses C:\\ as the disk root.
    On Linux: uses /opt/yantra if it exists, otherwise /.
    """
    cpu_pct = 0.0
    disk_free_gb = 0.0

    try:
        import psutil  # type: ignore

        cpu_pct = psutil.cpu_percent(interval=0.5)

        if os.name == "nt":
            disk_path = "C:\\"
        else:
            disk_path = "/opt/yantra" if os.path.exists("/opt/yantra") else "/"

        disk_free_gb = psutil.disk_usage(disk_path).free / (1024 ** 3)

    except Exception as e:
        log.warning(f"> HARDWARE: CPU/Disk probe failed: {e}")

    return cpu_pct, disk_free_gb


def probe_all() -> HardwareSnapshot:
    """Collect a full hardware snapshot."""
    gpu = probe_gpu()
    cpu_pct, disk_free_gb = probe_cpu_disk()
    return HardwareSnapshot(gpu=gpu, cpu_pct=cpu_pct, disk_free_gb=disk_free_gb)
