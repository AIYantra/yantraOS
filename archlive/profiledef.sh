#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# YantraOS — ArchISO Profile Definition
# Target: ~/archlive/profiledef.sh
# Milestone 6, Task 6.1
#
# This file is sourced by mkarchiso to define the ISO profile.
# It declares the ISO label, architecture, bootloader, and critically,
# the file_permissions associative array that locks down sensitive assets.
#
# CRITICAL: No trailing commas in bash associative arrays.
# A single trailing comma will halt mkarchiso entirely.
# ──────────────────────────────────────────────────────────────────────────────

# ── ISO Metadata ──────────────────────────────────────────────────────────────
iso_name="YantraOS"
iso_label="YANTRAOS_$(date +%Y%m)"
iso_publisher="YantraOS Project <https://yantraos.com>"
iso_application="YantraOS — AI-Agent Operating System"
iso_version="$(date +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
bootmodes=(
    'bios.syslinux'
    'uefi.grub'
)
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '15' '-b' '1M')

# ── File Permissions ──────────────────────────────────────────────────────────
# Format: ["/path"]="uid:gid:permissions"
#
# Security invariants:
#   • /etc/shadow and /etc/gshadow: 0400 (root-only read, no group, no other)
#   • /opt/yantra/core: 0755 (root-owned, world-executable but tamper-proof)
#   • /etc/yantra/host_secrets.env: 0600 (root-only read/write — API credentials)
#   • /run/yantra: 0770 (yantra group can read/write for UDS socket)
#   • /var/lib/yantra: 0770 (yantra group for ChromaDB persistence)
#   • Pacman hooks: 0644 (standard config file permissions)
#   • Polkit rules: 0644 (readable by polkitd)
#   • Systemd units: 0644 (standard unit file permissions)
#
# CRITICAL: NO TRAILING COMMAS. bash will abort on syntax errors.
# ──────────────────────────────────────────────────────────────────────────────
file_permissions=(
    # ── Security-critical files ───────────────────────────────────────────
    ["/etc/shadow"]="0:0:0400"
    ["/etc/gshadow"]="0:0:0400"
    ["/etc/yantra/host_secrets.env"]="0:0:0600"

    # ── YantraOS core ────────────────────────────────────────────────────
    ["/opt/yantra/core"]="0:0:0755"
    ["/opt/yantra/core/daemon.py"]="0:0:0755"
    ["/opt/yantra/core/cli.py"]="0:0:0755"
    ["/opt/yantra/core/engine.py"]="0:0:0644"
    ["/opt/yantra/core/sandbox.py"]="0:0:0644"
    ["/opt/yantra/core/btrfs_manager.py"]="0:0:0644"
    ["/opt/yantra/core/ipc_server.py"]="0:0:0644"
    ["/opt/yantra/core/hybrid_router.py"]="0:0:0644"
    ["/opt/yantra/core/vector_memory.py"]="0:0:0644"
    ["/opt/yantra/core/tui_shell.py"]="0:0:0644"
    ["/opt/yantra/core/config.py"]="0:0:0644"
    ["/opt/yantra/core/cloud.py"]="0:0:0644"
    ["/opt/yantra/core/hardware.py"]="0:0:0644"
    ["/opt/yantra/core/prompt.py"]="0:0:0644"
    ["/opt/yantra/core/fleet_manager.py"]="0:0:0644"
    ["/opt/yantra/core/installer.py"]="0:0:0644"

    # ── Virtual environment ──────────────────────────────────────────────
    ["/opt/yantra/venv"]="0:0:0755"

    # ── Runtime directories ──────────────────────────────────────────────
    # UID 999 = yantra_daemon, GID 999 = yantra
    ["/run/yantra"]="999:999:0770"
    ["/var/lib/yantra"]="999:999:0770"
    ["/var/lib/yantra/chromadb"]="999:999:0770"
    ["/var/lib/yantra/cache"]="999:999:0770"
    ["/var/log/yantra"]="999:999:0770"

    # ── Systemd, Polkit, Pacman hooks ────────────────────────────────────
    ["/etc/systemd/system/yantra.service"]="0:0:0644"
    ["/etc/polkit-1/rules.d/50-yantra-btrfs.rules"]="0:0:0644"
    ["/etc/pacman.d/hooks/00-yantra-autosnap.hook"]="0:0:0644"
    ["/etc/pacman.d/hooks/99-yantra-reload.hook"]="0:0:0644"

    # ── sysusers / tmpfiles ──────────────────────────────────────────────
    ["/usr/lib/sysusers.d/yantra.conf"]="0:0:0644"
    ["/usr/lib/tmpfiles.d/yantra.conf"]="0:0:0644"

    # ── Docker VFS config ──────────────────────────────────────────────
    ["/etc/docker/daemon.json"]="0:0:0644"

    # ── Boot scripts ─────────────────────────────────────────────────────
    ["/root/.automated_script.sh"]="0:0:0755"

    # ── yantra_user home ─────────────────────────────────────────────────
    ["/home/yantra_user"]="1000:1000:0700"
)
