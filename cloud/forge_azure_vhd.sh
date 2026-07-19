#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# forge_azure_vhd.sh — YantraOS Azure VHD Forge
#
# Produces an Azure Gen2 (UEFI) compatible fixed-size .vhd from scratch:
#
#   create_raw_image → partition_image → mount_loopback → create_subvolumes
#     → pacstrap_rootfs → inject_yantra_stack → configure_boot
#       → enable_services → seal_image → convert_to_vhd
#
# DESIGN PRINCIPLES
#   • Loopback-native: the entire rootfs is constructed inside a sparse .raw
#     image via losetup, eliminating the need for a physical target disk.
#   • BTRFS subvolume layout mirrors bare-metal YantraOS:
#       @                → /           (root filesystem)
#       @home            → /home       (user data)
#       @log             → /var/log    (journal + yantra logs)
#       @yantra-snapshots → /.snapshots (autonomous BTRFS snapshots)
#   • Headless by construction: no display manager, no TUI shell, no getty
#     autologin. The control API listens only on the VM loopback interface.
#   • SSH is excised: no sshd installed, no keys generated, no port 22.
#   • Azure Gen2 compliance: GPT partition table, EFI System Partition,
#     systemd-boot, fixed-size VHD via qemu-img convert.
#
# USAGE
#   sudo -E ./cloud/forge_azure_vhd.sh
#
# HOST REQUIREMENTS
#   Arch Linux host with: parted, btrfs-progs, dosfstools, arch-install-scripts
#   (pacstrap/arch-chroot), qemu-img, python, rsync.
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
IFS=$'\n\t'

# ── Static geometry ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
readonly SCRIPT_DIR

readonly IMAGE_SIZE_GB=30
readonly IMAGE_NAME="yantraos-azure"
readonly RAW_IMAGE="${SCRIPT_DIR}/cloud/${IMAGE_NAME}.raw"
readonly VHD_IMAGE="${SCRIPT_DIR}/cloud/${IMAGE_NAME}.vhd"
readonly MNT_ROOT="/tmp/yantra-vhd-rootfs-$$"
readonly VENV_TARGET="/opt/yantra/venv"
readonly SANDBOX_IMAGE="yantra-sandbox:3.20.3"
readonly SANDBOX_ARCHIVE="/opt/yantra/images/yantra-sandbox-3.20.3.tar"

# Partition geometry (MiB-aligned for Azure sector requirements).
readonly EFI_START_MIB=1
readonly EFI_END_MIB=513          # 512 MiB EFI System Partition
readonly ROOT_START_MIB=513       # Remainder → BTRFS root

# BTRFS subvolume topology — mirrors bare-metal YantraOS.
readonly -a BTRFS_SUBVOLS=("@" "@home" "@log" "@yantra-snapshots")

# Packages installed via pacstrap into the VHD rootfs.
readonly -a PACSTRAP_PACKAGES=(
  base linux linux-firmware
  btrfs-progs dosfstools
  docker python python-pip python-virtualenv
  cloud-init
  sudo less vim
)

# Systemd units enabled via systemctl --root=.
readonly -a YANTRA_SERVICES=(
  "yantra-provision-secrets.service" "yantra-sandbox-broker.service" "yantra.service"
  "yantra-telegram.service"
)
readonly -a BASE_SERVICES=(
  "docker.service" "systemd-networkd.service"
  "systemd-resolved.service" "cloud-init-local.service"
  "cloud-init-network.service" "cloud-config.service" "cloud-final.service"
)

# ── Mutable globals ──────────────────────────────────────────────────────────
LOOP_DEV=""        # /dev/loopN (populated after losetup)
EFI_PART=""        # /dev/loopNp1
ROOT_PART=""       # /dev/loopNp2

# ── Logging (mirrors forge_sovereign_iso.sh) ─────────────────────────────────
readonly C_RED='\033[0;31m' C_GRN='\033[0;32m' C_YEL='\033[1;33m' C_CYN='\033[0;36m' C_NC='\033[0m'
log_info() { echo -e "${C_CYN}[INFO]${C_NC} $*"; }
log_ok()   { echo -e "${C_GRN}[ OK ]${C_NC} $*"; }
log_warn() { echo -e "${C_YEL}[WARN]${C_NC} $*" >&2; }
log_fatal(){ echo -e "${C_RED}[FATAL]${C_NC} $*" >&2; }
die()      { log_fatal "$*"; exit 1; }

# ── Lifecycle cleanup ─────────────────────────────────────────────────────────
# Tear down mounts and loopback on any exit (success or failure).
cleanup() {
  local rc=$?
  log_info "Cleanup: tearing down mounts and loopback..."

  # Unmount nested mounts in reverse order.
  local mp
  for mp in \
    "${MNT_ROOT}/boot/efi" \
    "${MNT_ROOT}/home" \
    "${MNT_ROOT}/var/log" \
    "${MNT_ROOT}/.snapshots" \
    "${MNT_ROOT}/proc" \
    "${MNT_ROOT}/sys" \
    "${MNT_ROOT}/dev/pts" \
    "${MNT_ROOT}/dev" \
    "${MNT_ROOT}/run" \
    "${MNT_ROOT}"; do
    mountpoint -q "${mp}" 2>/dev/null && umount -lf "${mp}" 2>/dev/null || true
  done

  # Detach loopback device.
  [[ -n "${LOOP_DEV}" && -b "${LOOP_DEV}" ]] && losetup -d "${LOOP_DEV}" 2>/dev/null || true

  # Remove mount point.
  [[ -d "${MNT_ROOT}" ]] && rm -rf -- "${MNT_ROOT}" || true

  return $rc
}
trap cleanup EXIT

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — verify_dependencies
# ══════════════════════════════════════════════════════════════════════════════
verify_dependencies() {
  log_info "═══ PHASE 1: verify_dependencies ═══"

  [[ "${EUID}" -eq 0 ]] || die "Must run as root (UID 0). Re-run: sudo -E $0"
  log_ok "Root privileges confirmed."

  local -A REQUIRED_CMDS=(
    [parted]="parted"
    [mkfs.vfat]="dosfstools"
    [mkfs.btrfs]="btrfs-progs"
    [pacstrap]="arch-install-scripts"
    [arch-chroot]="arch-install-scripts"
    [qemu-img]="qemu-img"
    [rsync]="rsync"
    [losetup]="util-linux"
    [docker]="docker"
  )
  local missing=() cmd pkg
  for cmd in "${!REQUIRED_CMDS[@]}"; do
    pkg="${REQUIRED_CMDS[$cmd]}"
    command -v "${cmd}" >/dev/null 2>&1 || missing+=("${pkg} (provides '${cmd}')")
  done
  if (( ${#missing[@]} > 0 )); then
    printf '  - %s\n' "${missing[@]}" >&2
    die "Missing dependencies. Install the listed packages and retry."
  fi
  log_ok "All build dependencies satisfied."

  # Source tree sanity.
  local source_dir
  for source_dir in core scripts deploy; do
    [[ -d "${SCRIPT_DIR}/${source_dir}" ]] \
      || die "Required source directory missing: ${SCRIPT_DIR}/${source_dir}"
  done
  [[ -f "${SCRIPT_DIR}/requirements.txt" ]] \
    || die "Required dependency manifest missing: ${SCRIPT_DIR}/requirements.txt"
  [[ -f "${SCRIPT_DIR}/requirements.lock" ]] \
    || die "Required dependency lock missing: ${SCRIPT_DIR}/requirements.lock"
  log_ok "Source tree verified."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — create_raw_image
#   Allocate a sparse .raw image file with dd and partition it with parted.
# ══════════════════════════════════════════════════════════════════════════════
create_raw_image() {
  log_info "═══ PHASE 2: create_raw_image ═══"

  # 2.1 — Create sparse image (dd with seek = instant, no disk fill).
  rm -f -- "${RAW_IMAGE}"
  dd if=/dev/zero of="${RAW_IMAGE}" bs=1M count=0 seek=$((IMAGE_SIZE_GB * 1024)) status=none
  log_ok "Sparse .raw image created: ${RAW_IMAGE} (${IMAGE_SIZE_GB}GB)"

  # 2.2 — GPT partition table (Azure Gen2 mandates GPT + UEFI).
  parted -s "${RAW_IMAGE}" \
    mklabel gpt \
    mkpart "EFI"  fat32 "${EFI_START_MIB}MiB" "${EFI_END_MIB}MiB" \
    set 1 esp on \
    mkpart "root" btrfs "${ROOT_START_MIB}MiB" 100%
  log_ok "GPT partition table written (512MiB EFI + remainder BTRFS root)."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — mount_loopback
#   Attach the .raw image via losetup, format partitions, mount BTRFS with
#   the subvolume topology.
# ══════════════════════════════════════════════════════════════════════════════
mount_loopback() {
  log_info "═══ PHASE 3: mount_loopback ═══"

  # 3.1 — Attach loopback with partition scanning.
  LOOP_DEV="$(losetup --find --show --partscan "${RAW_IMAGE}")"
  EFI_PART="${LOOP_DEV}p1"
  ROOT_PART="${LOOP_DEV}p2"
  log_ok "Loopback attached: ${LOOP_DEV}"

  # Wait for partition devices to appear.
  local retries=0
  while [[ ! -b "${ROOT_PART}" ]] && (( retries < 10 )); do
    sleep 0.5; retries=$((retries + 1))
  done
  [[ -b "${EFI_PART}" && -b "${ROOT_PART}" ]] \
    || die "Partition devices not found: ${EFI_PART}, ${ROOT_PART}"
  log_ok "Partition devices ready: ${EFI_PART}, ${ROOT_PART}"

  # 3.2 — Format partitions.
  mkfs.vfat -F 32 -n "EFI" "${EFI_PART}" >/dev/null
  log_ok "EFI partition formatted (FAT32)."

  mkfs.btrfs -f -L "yantraos-root" "${ROOT_PART}" >/dev/null
  log_ok "Root partition formatted (BTRFS)."

  # 3.3 — Create BTRFS subvolumes.
  install -dm755 "${MNT_ROOT}"
  mount -t btrfs "${ROOT_PART}" "${MNT_ROOT}"
  log_info "Creating BTRFS subvolumes..."
  local subvol
  for subvol in "${BTRFS_SUBVOLS[@]}"; do
    btrfs subvolume create "${MNT_ROOT}/${subvol}"
    log_info "  ↳ ${subvol}"
  done
  umount "${MNT_ROOT}"
  log_ok "BTRFS subvolumes created: ${BTRFS_SUBVOLS[*]}"

  # 3.4 — Remount with @ as root, then mount remaining subvolumes.
  mount -t btrfs -o subvol=@,compress=zstd:1,noatime "${ROOT_PART}" "${MNT_ROOT}"

  install -dm755 "${MNT_ROOT}/home"
  mount -t btrfs -o subvol=@home,compress=zstd:1,noatime "${ROOT_PART}" "${MNT_ROOT}/home"

  install -dm755 "${MNT_ROOT}/var/log"
  mount -t btrfs -o subvol=@log,compress=zstd:1,noatime "${ROOT_PART}" "${MNT_ROOT}/var/log"

  install -dm755 "${MNT_ROOT}/.snapshots"
  mount -t btrfs -o subvol=@yantra-snapshots,compress=zstd:1,noatime "${ROOT_PART}" "${MNT_ROOT}/.snapshots"

  # 3.5 — Mount EFI.
  install -dm755 "${MNT_ROOT}/boot/efi"
  mount "${EFI_PART}" "${MNT_ROOT}/boot/efi"

  log_ok "All filesystems mounted under ${MNT_ROOT}."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — pacstrap_rootfs
#   Install the base Arch Linux system + YantraOS runtime packages into the
#   loopback-mounted rootfs via pacstrap.
# ══════════════════════════════════════════════════════════════════════════════
pacstrap_rootfs() {
  log_info "═══ PHASE 4: pacstrap_rootfs ═══"

  log_info "Pacstrapping ${#PACSTRAP_PACKAGES[@]} packages into ${MNT_ROOT}..."
  pacstrap -c "${MNT_ROOT}" "${PACSTRAP_PACKAGES[@]}"
  log_ok "Pacstrap completed."

  # 4.1 — Generate fstab from mounted state.
  genfstab -U "${MNT_ROOT}" >> "${MNT_ROOT}/etc/fstab"
  log_ok "fstab generated."

  # 4.2 — Basic system configuration.
  echo "yantraos-cloud" > "${MNT_ROOT}/etc/hostname"
  ln -sf /usr/share/zoneinfo/UTC "${MNT_ROOT}/etc/localtime"

  # Locale.
  sed -i 's/^#en_US.UTF-8/en_US.UTF-8/' "${MNT_ROOT}/etc/locale.gen"
  arch-chroot "${MNT_ROOT}" locale-gen >/dev/null
  echo "LANG=en_US.UTF-8" > "${MNT_ROOT}/etc/locale.conf"

  # 4.3 — Networking: enable DHCP via systemd-networkd for Azure's virtual NIC.
  install -dm755 "${MNT_ROOT}/etc/systemd/network"
  cat > "${MNT_ROOT}/etc/systemd/network/20-azure-dhcp.network" <<'NETEOF'
[Match]
Name=en* eth*

[Network]
DHCP=yes
IPv6AcceptRA=yes

[DHCPv4]
UseDNS=yes
UseHostname=yes
NETEOF
  log_ok "Systemd-networkd DHCP configuration installed."

  # 4.4 — DNS resolution via systemd-resolved.
  ln -sf /run/systemd/resolve/stub-resolv.conf "${MNT_ROOT}/etc/resolv.conf"
  log_ok "Base system configured (hostname, locale, timezone, network)."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5 — inject_yantra_stack
#   Deploy the Kriya Loop daemon, sandbox broker, Host Executor, venv, and
#   sysusers/tmpfiles into the VHD rootfs. Credentials never enter the image.
# ══════════════════════════════════════════════════════════════════════════════
inject_yantra_stack() {
  log_info "═══ PHASE 5: inject_yantra_stack ═══"

  # 5.1 — Inject codebase into /opt/yantra/ (mirrors forge_sovereign_iso.sh §2.4).
  local dest="${MNT_ROOT}/opt/yantra"
  install -dm755 "${dest}"
  local sub src
  for sub in core scripts deploy; do
    src="${SCRIPT_DIR}/${sub}"
    [[ -d "${src}" ]] || die "Required source directory missing: ${src}"
    rsync -a --chown=root:root --delete \
      --exclude='.env*' --exclude='*.pem' --exclude='*.key' \
      --exclude='*.db' --exclude='*.sqlite*' \
      --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.json' \
      "${src}/" "${dest}/${sub}/"
    log_info "  ↳ rsynced ${sub}/ → /opt/yantra/${sub}/"
  done
  # requirements.txt for in-chroot pip.
  [[ -f "${SCRIPT_DIR}/requirements.txt" ]] \
    || die "Required dependency manifest missing: ${SCRIPT_DIR}/requirements.txt"
  install -Dm644 "${SCRIPT_DIR}/requirements.txt" "${dest}/requirements.txt"
  install -Dm644 "${SCRIPT_DIR}/requirements.lock" "${dest}/requirements.lock"
  log_ok "Codebase injected into /opt/yantra/."

  local sandbox_archive="${MNT_ROOT}${SANDBOX_ARCHIVE}"
  install -dm755 "$(dirname -- "${sandbox_archive}")"
  docker build --pull --tag "${SANDBOX_IMAGE}" "${SCRIPT_DIR}/core/sandbox"
  docker image inspect "${SANDBOX_IMAGE}" >/dev/null
  docker save --output "${sandbox_archive}" "${SANDBOX_IMAGE}"
  chmod 0644 "${sandbox_archive}"
  log_ok "Pinned sandbox image staged at ${SANDBOX_ARCHIVE}."

  # 5.2 — Install sysusers.d + tmpfiles.d (system user/group provisioning).
  install -Dm644 "${SCRIPT_DIR}/deploy/sysusers.d/yantra.conf" \
    "${MNT_ROOT}/usr/lib/sysusers.d/yantra.conf"
  install -Dm644 "${SCRIPT_DIR}/deploy/tmpfiles.d/yantra.conf" \
    "${MNT_ROOT}/usr/lib/tmpfiles.d/yantra.conf"
  # /etc/yantra/secrets.env is intentionally absent. Provision it root:root
  # 0600 after VM creation (for example through Key Vault), then restart Yantra.
  log_ok "sysusers.d + tmpfiles.d installed."

  # 5.3 — Create system users/groups NOW inside the chroot so UIDs exist
  #        for subsequent chown operations.
  arch-chroot "${MNT_ROOT}" systemd-sysusers >/dev/null
  arch-chroot "${MNT_ROOT}" systemd-tmpfiles --create >/dev/null
  log_ok "System users provisioned via systemd-sysusers."

  # 5.4 — Install systemd unit files.
  local sysd="${MNT_ROOT}/etc/systemd/system"
  install -dm755 "${sysd}"
  local unit
  for unit in "${YANTRA_SERVICES[@]}"; do
    local src="${SCRIPT_DIR}/deploy/systemd/${unit}"
    [[ -f "${src}" ]] || die "Required unit file missing: ${src}"
    install -Dm644 "${src}" "${sysd}/${unit}"
    log_info "  ↳ Installed ${unit}"
  done
  log_ok "Systemd unit files installed."

  # 5.5 — Build Python venv inside the chroot (same pattern as forge_sovereign_iso.sh §3).
  log_info "Building Python venv inside chroot..."
  install -Dm644 /etc/resolv.conf "${MNT_ROOT}/etc/resolv.conf" 2>/dev/null || true
  arch-chroot "${MNT_ROOT}" /bin/bash -s <<'CHROOT'
set -euo pipefail
export GIT_HTTP_VERSION=1.1
VENV=/opt/yantra/venv
install -dm755 /opt/yantra
python -m venv "${VENV}"
"${VENV}/bin/pip" install --require-hashes -r /opt/yantra/requirements.lock --prefer-binary --quiet --retries 10 --timeout 120
CHROOT
  log_ok "Python venv compiled inside chroot."

  # 5.6 — Global binary wrapper: /usr/bin/yantra-snapshot.
  local snap_bin="${MNT_ROOT}/usr/bin/yantra-snapshot"
  cat > "${snap_bin}" <<'SNAPEOF'
#!/bin/bash
# YantraOS — Global BTRFS Snapshot Wrapper
exec /opt/yantra/venv/bin/python3 /opt/yantra/core/cli_snapshot.py "$@"
SNAPEOF
  chmod 0755 "${snap_bin}"
  log_ok "/usr/bin/yantra-snapshot wrapper provisioned."

  # 5.7 — Persistent state directories.
  install -dm750 "${MNT_ROOT}/var/lib/yantra" "${MNT_ROOT}/var/log/yantra"
  # Apply BTRFS nodatacow for ChromaDB.
  install -dm750 "${MNT_ROOT}/var/lib/yantra/chromadb"
  arch-chroot "${MNT_ROOT}" chattr +C /var/lib/yantra/chromadb
  # Ownership: yantra_daemon:yantra (best effort — UID/GID may not resolve outside chroot).
  arch-chroot "${MNT_ROOT}" chown -R yantra_daemon:yantra /var/lib/yantra /var/log/yantra
  log_ok "Persistent state directories provisioned."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 6 — configure_boot
#   Install and configure systemd-boot for UEFI execution on Azure Gen2 VMs.
# ══════════════════════════════════════════════════════════════════════════════
configure_boot() {
  log_info "═══ PHASE 6: configure_boot ═══"

  # 6.1 — Install systemd-boot into the EFI System Partition.
  arch-chroot "${MNT_ROOT}" bootctl install --esp-path=/boot/efi
  log_ok "systemd-boot installed to ESP."

  # 6.2 — Determine the root partition UUID for the boot loader entry.
  local root_uuid
  root_uuid="$(blkid -s UUID -o value "${ROOT_PART}")"
  [[ -n "${root_uuid}" ]] || die "Failed to determine root partition UUID."
  log_info "Root partition UUID: ${root_uuid}"

  # 6.3 — Loader configuration.
  cat > "${MNT_ROOT}/boot/efi/loader/loader.conf" <<LOADEREOF
default yantraos.conf
timeout 0
console-mode max
editor  no
LOADEREOF
  log_ok "systemd-boot loader.conf written."

  # 6.4 — Boot entry for YantraOS.
  install -dm755 "${MNT_ROOT}/boot/efi/loader/entries"
  cat > "${MNT_ROOT}/boot/efi/loader/entries/yantraos.conf" <<ENTRYEOF
title   YantraOS Cloud Node
linux   /vmlinuz-linux
initrd  /initramfs-linux.img
options root=UUID=${root_uuid} rootflags=subvol=@,compress=zstd:1 rw quiet console=ttyS0,115200n8 earlyprintk=ttyS0,115200 rootdelay=300
ENTRYEOF
  log_ok "Boot entry created (console=ttyS0 for Azure serial console)."

  # 6.5 — Copy kernel + initramfs to ESP (systemd-boot expects them on the ESP).
  local kernel initrd
  kernel="$(find "${MNT_ROOT}/boot" -maxdepth 1 -name 'vmlinuz-linux' -print -quit)"
  initrd="$(find "${MNT_ROOT}/boot" -maxdepth 1 -name 'initramfs-linux.img' -print -quit)"
  [[ -f "${kernel}" ]] || die "Kernel not found in ${MNT_ROOT}/boot/"
  [[ -f "${initrd}" ]] || die "Initramfs not found in ${MNT_ROOT}/boot/"
  cp -- "${kernel}" "${MNT_ROOT}/boot/efi/vmlinuz-linux"
  cp -- "${initrd}" "${MNT_ROOT}/boot/efi/initramfs-linux.img"
  log_ok "Kernel + initramfs copied to ESP."

  # 6.6 — Regenerate initramfs with BTRFS module included.
  # Ensure the mkinitcpio HOOKS include btrfs support.
  sed -i 's/^MODULES=.*/MODULES=(btrfs)/' "${MNT_ROOT}/etc/mkinitcpio.conf"
  arch-chroot "${MNT_ROOT}" mkinitcpio -P >/dev/null 2>&1
  # Re-copy the regenerated initramfs to ESP.
  cp -- "${MNT_ROOT}/boot/initramfs-linux.img" "${MNT_ROOT}/boot/efi/initramfs-linux.img"
  log_ok "Initramfs regenerated with BTRFS module and re-synced to ESP."

  # Keep the ESP kernel/initramfs synchronized after every Linux package update.
  install -dm755 "${MNT_ROOT}/usr/local/sbin" "${MNT_ROOT}/etc/pacman.d/hooks"
  cat > "${MNT_ROOT}/usr/local/sbin/yantra-sync-esp" <<'SYNCEOF'
#!/usr/bin/env bash
set -euo pipefail
install -Dm644 /boot/vmlinuz-linux /boot/efi/vmlinuz-linux
install -Dm644 /boot/initramfs-linux.img /boot/efi/initramfs-linux.img
SYNCEOF
  chmod 0755 "${MNT_ROOT}/usr/local/sbin/yantra-sync-esp"
  cat > "${MNT_ROOT}/etc/pacman.d/hooks/95-yantra-sync-esp.hook" <<'HOOKEOF'
[Trigger]
Operation = Install
Operation = Upgrade
Type = Package
Target = linux

[Action]
Description = Synchronizing YantraOS kernel and initramfs to ESP
When = PostTransaction
Exec = /usr/local/sbin/yantra-sync-esp
HOOKEOF
  chmod 0644 "${MNT_ROOT}/etc/pacman.d/hooks/95-yantra-sync-esp.hook"
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 7 — enable_services
#   Enable all YantraOS + base services via systemctl enable --root=...
#   CRITICAL: This uses --root= to manipulate the offline rootfs symlinks
#   without requiring a running systemd inside the chroot.
# ══════════════════════════════════════════════════════════════════════════════
enable_services() {
  log_info "═══ PHASE 7: enable_services ═══"

  # 7.1 — Enable base distribution services.
  local unit
  for unit in "${BASE_SERVICES[@]}"; do
    systemctl enable --root="${MNT_ROOT}" "${unit}"
    log_info "  ↳ ${unit}"
  done

  # 7.2 — CRITICAL: Enable YantraOS services.
  for unit in "${YANTRA_SERVICES[@]}"; do
    systemctl enable --root="${MNT_ROOT}" "${unit}"
    log_info "  ↳ ${unit} (CRITICAL — Kriya Loop)"
  done
  log_ok "All services enabled: ${#BASE_SERVICES[@]} base + ${#YANTRA_SERVICES[@]} YantraOS."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 8 — seal_image
#   Final sanitation pass, unmount all filesystems, detach loopback.
# ══════════════════════════════════════════════════════════════════════════════
seal_image() {
  log_info "═══ PHASE 8: seal_image ═══"

  # 8.1 — Amnesia Protocol: purge host state bleed.
  rm -f -- "${MNT_ROOT}/etc/resolv.conf" 2>/dev/null || true
  find "${MNT_ROOT}/opt/yantra/" -not -path '*/venv/*' \
    \( -name '*.json' -o -name '*.pyc' \) -type f -delete 2>/dev/null || true
  find "${MNT_ROOT}/opt/yantra/" -type d -name '__pycache__' \
    -prune -exec rm -rf {} + 2>/dev/null || true
  # Restore symlink for systemd-resolved.
  ln -sf /run/systemd/resolve/stub-resolv.conf "${MNT_ROOT}/etc/resolv.conf"
  log_ok "Amnesia Protocol: host state purged."

  # 8.2 — Lock root password (headless node — no interactive login).
  arch-chroot "${MNT_ROOT}" passwd -l root >/dev/null
  log_ok "Root account locked (headless node — SSH excised)."

  # 8.3 — Sync and unmount.
  sync
  log_info "Unmounting filesystems..."
  local mp
  for mp in \
    "${MNT_ROOT}/boot/efi" \
    "${MNT_ROOT}/home" \
    "${MNT_ROOT}/var/log" \
    "${MNT_ROOT}/.snapshots" \
    "${MNT_ROOT}"; do
    mountpoint -q "${mp}" 2>/dev/null && umount "${mp}" || true
  done
  log_ok "All filesystems unmounted."

  # 8.4 — Detach loopback.
  losetup -d "${LOOP_DEV}"
  log_ok "Loopback detached: ${LOOP_DEV}"
  LOOP_DEV=""  # Disarm the cleanup trap.
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 9 — convert_to_vhd
#   Convert the .raw image to a fixed-size .vhd (Azure mandates fixed VHDs).
#   Azure Gen2 VMs require: VHD format, fixed subformat, 1MB-aligned size.
# ══════════════════════════════════════════════════════════════════════════════
convert_to_vhd() {
  log_info "═══ PHASE 9: convert_to_vhd ═══"

  # 9.1 — Ensure the raw image size is 1MB-aligned (Azure requirement).
  local raw_size_bytes
  raw_size_bytes="$(stat --format='%s' "${RAW_IMAGE}")"
  local aligned_size=$(( (raw_size_bytes + 1048575) / 1048576 * 1048576 ))
  if (( raw_size_bytes != aligned_size )); then
    log_info "Aligning .raw to 1MB boundary: ${raw_size_bytes} → ${aligned_size} bytes"
    qemu-img resize -f raw "${RAW_IMAGE}" "${aligned_size}" >/dev/null
  fi

  # 9.2 — Convert raw → fixed VHD.
  rm -f -- "${VHD_IMAGE}"
  qemu-img convert -f raw -O vpc -o subformat=fixed,force_size "${RAW_IMAGE}" "${VHD_IMAGE}"
  log_ok "VHD created: ${VHD_IMAGE}"

  # 9.3 — Verify the VHD.
  qemu-img info "${VHD_IMAGE}" | head -6
  local vhd_size
  vhd_size="$(du -h "${VHD_IMAGE}" | cut -f1)"
  log_ok "Fixed VHD verified: ${vhd_size}"

  # 9.4 — Clean up the intermediate .raw (the VHD is the deliverable).
  rm -f -- "${RAW_IMAGE}"
  log_ok "Intermediate .raw removed. Final artifact: ${VHD_IMAGE}"
}

# ══════════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════════
main() {
  log_info "════════════════════════════════════════════════════════════════"
  log_info "  YantraOS Azure VHD Forge"
  log_info "  Target: Azure Gen2 VM (UEFI) — Headless Autonomous Node"
  log_info "════════════════════════════════════════════════════════════════"

  verify_dependencies
  create_raw_image
  mount_loopback
  pacstrap_rootfs
  inject_yantra_stack
  configure_boot
  enable_services
  seal_image
  convert_to_vhd

  log_ok "════════════════════════════════════════════════════════════════"
  log_ok "  VHD Forge complete."
  log_ok "  Artifact: ${VHD_IMAGE}"
  log_ok "  Next: Run cloud/azure_vm_deploy.azcli to deploy to Azure."
  log_ok "════════════════════════════════════════════════════════════════"
}

main "$@"
