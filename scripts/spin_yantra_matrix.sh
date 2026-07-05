#!/usr/bin/env bash
# YantraOS — QEMU Hypervisor Matrix Ignition Script
# Boots the compiled ArchLinux ISO in a strict UEFI environment
# to validate the installer and BTRFS atomic layout.

set -e

# Change to the YantraOS project root
cd "$(dirname "$0")/.."

echo "> MATRIX: Initializing Hypervisor Substrate..."

# 1. Ensure the QCOW2 virtual disk exists
DISK_IMG="yantra_substrate.qcow2"
if [ ! -f "$DISK_IMG" ]; then
    echo "> MATRIX: Virtual disk not found. Generating a 64GB QCOW2 substrate..."
    qemu-img create -f qcow2 "$DISK_IMG" 64G
else
    echo "> MATRIX: Existing substrate found ($DISK_IMG)."
fi

# 2. Locate the most recently compiled YantraOS ISO
echo "> MATRIX: Scanning for YantraOS ISO..."
ISO_PATH=$(ls -t /opt/yantra-releases/yantraos-*.iso 2>/dev/null | head -n 1 || true)

if [ -z "$ISO_PATH" ]; then
    echo "> FATAL: No YantraOS ISO found in /opt/yantra-releases/"
    echo "> Action: Run the archiso build pipeline before igniting the matrix."
    exit 1
fi

echo "> MATRIX: Igniting ISO -> $ISO_PATH"

OVMF_PATH=""
for path in /usr/share/edk2/x64/OVMF_CODE.4m.fd /usr/share/edk2/x64/OVMF_CODE.fd /usr/share/ovmf/x64/OVMF_CODE.fd /usr/share/edk2-ovmf/x64/OVMF_CODE.fd; do
    if [ -f "$path" ]; then
        OVMF_PATH="$path"
        break
    fi
done

if [ -z "$OVMF_PATH" ]; then
    echo "> FATAL: Could not find OVMF UEFI firmware on this host."
    exit 1
fi
echo "> MATRIX: Found UEFI firmware at $OVMF_PATH"

# 3. Boot QEMU with KVM, strict UEFI, and port forwarding
# Host TCP 50000 -> VM 50000 (Telemetry IPC)
# Host TCP 2222  -> VM 22    (SSH Fleet Access)
echo "> MATRIX: Engaging KVM orchestration..."
qemu-system-x86_64 \
    -nographic \
    -enable-kvm \
    -m 8G \
    -smp 4 \
    -drive if=pflash,format=raw,readonly=on,file="$OVMF_PATH" \
    -drive file="$DISK_IMG",if=virtio,format=qcow2 \
    -cdrom "$ISO_PATH" \
    -netdev user,id=net0,hostfwd=tcp::50000-:50000,hostfwd=tcp::2222-:22 \
    -device virtio-net-pci,netdev=net0

echo "> MATRIX: Hypervisor session terminated gracefully."
