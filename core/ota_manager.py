"""
YantraOS — OTA Manager
Target: /opt/yantra/core/ota_manager.py

Handles autonomous OS updates (pacman -Syu) on Arch Linux.
This module executes strictly within the host environment, leveraging
pre-existing BTRFS snapshot pacman hooks and Polkit passwordless sudo rules
for the `yantra_daemon` user.
"""

import asyncio
import logging

log = logging.getLogger("yantra.ota_manager")

class OTAUpdateError(Exception):
    """Raised when the OTA process encounters a non-zero exit code."""
    def __init__(self, message: str, stderr_trace: str):
        super().__init__(message)
        self.stderr_trace = stderr_trace


class OTAManager:
    """
    Manages Over-The-Air system updates via Arch Linux's pacman.
    Captures subprocess output asynchronously to avoid blocking the Kriya Loop.
    """

    @staticmethod
    async def trigger_system_update() -> str:
        """
        Executes `sudo pacman -Syu --noconfirm` asynchronously.
        Returns the captured stdout on success.
        Raises OTAUpdateError on failure.
        """
        log.info("> OTA: Initiating system update sequence...")
        
        # We use asyncio.create_subprocess_exec to ensure strictly isolated argument passing,
        # preventing any string-interpolation shell injection attacks.
        process = await asyncio.create_subprocess_exec(
            "sudo", "pacman", "-Syu", "--noconfirm",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout_buffer = []
        stderr_buffer = []

        async def read_stream(stream: asyncio.StreamReader | None, buffer: list[str], prefix: str):
            if stream is None:
                return
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode('utf-8', errors='replace').rstrip()
                buffer.append(line)
                # Stream to daemon log in real-time
                if prefix == "ERR":
                    log.error(f"> OTA [{prefix}]: {line}")
                else:
                    log.debug(f"> OTA [{prefix}]: {line}")

        # Read both streams concurrently to prevent deadlocks
        await asyncio.gather(
            read_stream(process.stdout, stdout_buffer, "OUT"),
            read_stream(process.stderr, stderr_buffer, "ERR")
        )

        return_code = await process.wait()
        
        full_stdout = "\n".join(stdout_buffer)
        full_stderr = "\n".join(stderr_buffer)

        if return_code != 0:
            log.error(f"> OTA: Update failed with exit code {return_code}.")
            raise OTAUpdateError(
                message=f"Pacman transaction failed with code {return_code}",
                stderr_trace=full_stderr or full_stdout
            )
        
        log.info("> OTA: System update completed successfully.")
        return full_stdout
