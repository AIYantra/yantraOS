import asyncio
import os
import subprocess
import logging
from typing import Callable, Optional

log = logging.getLogger("yantra.installer")

async def run_cmd_async(cmd: str, log_cb: Callable[[str], None], env: dict = None) -> int:
    """Run a shell command asynchronously and stream its output to a callback."""
    log_cb(f"> Running: {cmd}")
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        executable="/bin/bash"
    )

    while True:
        line = await process.stdout.readline()
        if not line:
            break
        decoded = line.decode('utf-8', errors='replace').rstrip()
        log_cb(f"  {decoded}")

    return await process.wait()

async def execute_install(log_callback: Callable[[str], None]) -> bool:
    """
    Executes the bare-metal installation pipeline:
    1. Detect disk
    2. Partition & Format (BTRFS)
    3. Mount with subvolumes
    4. Rsync rootfs
    5. Install Grub
    """
    log_callback("> INITIATING YANTRA OS BARE-METAL INSTALLATION")
    
    # 1. Drive Detection
    # Look for the primary internal drive. Typical naming: nvme0n1 or sda.
    # Exclude loop devices or obvious USBs if possible, just naive matching for now.
    proc = await asyncio.create_subprocess_shell(
        "lsblk -d -n -o NAME,TYPE | grep disk | awk '{print $1}'",
        stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    disks = stdout.decode().strip().split('\n')
    
    target_disk = None
    for d in disks:
        if d.startswith("nvme0n1") or d.startswith("sda"):
            target_disk = f"/dev/{d}"
            break
    
    if not target_disk:
        log_callback(f"> ERROR: Could not identify a valid target disk among: {disks}")
        return False
        
    log_callback(f"> Target disk identified: {target_disk}")
    
    # Check if disk has partitions (simple warning/wipe concept)
    # WARNING: THIS IS DESTRUCTIVE
    
    commands = [
        f"swapoff -a || true",
        f"umount -R /mnt || true",
        
        # 2. Wipe and Partition
        f"wipefs -a {target_disk}",
        f"sgdisk -Z {target_disk}",
        # Create EFI partition (type EF00) - 512MB
        f"sgdisk -n 1:0:+512M -t 1:ef00 -c 1:'EFI System Partition' {target_disk}",
        # Create Root partition (type 8300) - rest of disk
        f"sgdisk -n 2:0:0 -t 2:8300 -c 2:'YantraOS Root' {target_disk}",
        f"partprobe {target_disk}"
    ]
    
    for cmd in commands:
        code = await run_cmd_async(cmd, log_callback)
        if code != 0 and "umount" not in cmd and "swapoff" not in cmd:
            log_callback(f"> ERROR: Command failed with exit code {code}: {cmd}")
            return False

    # Allow kernel to see partitions
    await asyncio.sleep(2)
    
    # Identify partition paths (nvme0n1p1 vs sda1)
    if "nvme" in target_disk:
        part_efi = f"{target_disk}p1"
        part_root = f"{target_disk}p2"
    else:
        part_efi = f"{target_disk}1"
        part_root = f"{target_disk}2"
        
    log_callback(f"> EFI Partition: {part_efi}")
    log_callback(f"> Root Partition: {part_root}")
    
    # 3. Format & Mount
    format_cmds = [
        f"mkfs.fat -F32 {part_efi}",
        f"mkfs.btrfs -f {part_root}"
    ]
    
    for cmd in format_cmds:
        code = await run_cmd_async(cmd, log_callback)
        if code != 0:
            return False
            
    # BTRFS Subvolumes
    log_callback("> Configuring BTRFS Subvolumes (@, @home, @log)")
    subvol_cmds = [
        f"mount {part_root} /mnt",
        f"btrfs subvolume create /mnt/@",
        f"btrfs subvolume create /mnt/@home",
        f"btrfs subvolume create /mnt/@log",
        f"umount /mnt",
        
        # Mount them correctly
        f"mount -o noatime,compress=zstd,space_cache=v2,subvol=@ {part_root} /mnt",
        f"mkdir -p /mnt/home",
        f"mount -o noatime,compress=zstd,space_cache=v2,subvol=@home {part_root} /mnt/home",
        f"mkdir -p /mnt/var/log",
        f"mount -o noatime,compress=zstd,space_cache=v2,subvol=@log {part_root} /mnt/var/log",
        
        # Mount EFI
        f"mkdir -p /mnt/boot/efi",
        f"mount {part_efi} /mnt/boot/efi"
    ]
    
    for cmd in subvol_cmds:
        code = await run_cmd_async(cmd, log_callback)
        if code != 0:
            return False
            
    # 4. Rsync RootFS
    log_callback("> Cloning Live System to Target Disk (This will take a while...)")
    rsync_cmd = "rsync -aAXv --exclude={'/dev/*','/proc/*','/sys/*','/tmp/*','/run/*','/mnt/*','/media/*','/lost+found'} / /mnt"
    code = await run_cmd_async(rsync_cmd, log_callback)
    if code != 0:
        log_callback(f"> ERROR: Rsync failed with code {code}")
        return False
        
    # 5. Bootloader & Fstab
    log_callback("> Generating fstab and installing GRUB Bootloader")
    boot_cmds = [
        f"genfstab -U /mnt > /mnt/etc/fstab",
        f"arch-chroot /mnt grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=YantraOS --recheck",
        f"arch-chroot /mnt grub-mkconfig -o /boot/grub/grub.cfg"
    ]
    
    for cmd in boot_cmds:
        code = await run_cmd_async(cmd, log_callback)
        if code != 0:
            return False
            
    # Cleanup
    log_callback("> Installation Complete! Cleaning up mounts...")
    await run_cmd_async("umount -R /mnt", log_callback)
    
    log_callback("> YANTRA OS INSTALLED SUCCESSFULLY. YOU MAY REBOOT.")
    return True
