#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="yantraos"
iso_label="YANTRA_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="YantraOS <https://yantraos.com>"
iso_application="YantraOS — Autonomous Edge Operating System"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'xz' '-Xbcj' 'x86' '-b' '1M' '-Xdict-size' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
file_permissions=(
  # ── System security ────────────────────────────────────────────────────────
  ["/etc/shadow"]="0:0:0400"
  ["/root"]="0:0:0750"
  ["/root/.automated_script.sh"]="0:0:0755"
  ["/root/.gnupg"]="0:0:0700"

  # ── Arch ISO standard utilities ────────────────────────────────────────────
  ["/usr/local/bin/choose-mirror"]="0:0:0755"
  ["/usr/local/bin/Installation_guide"]="0:0:0755"
  ["/usr/local/bin/livecd-sound"]="0:0:0755"

  # ── YantraOS core daemon tree ──────────────────────────────────────────────
  # Root-owned, world-readable/executable. The daemon user (yantra_daemon)
  # can READ and EXECUTE but cannot modify the codebase at runtime.
  ["/opt/yantra"]="0:0:0755"
  ["/opt/yantra/core"]="0:0:0755"
  ["/opt/yantra/deploy"]="0:0:0755"
  ["/opt/yantra/scripts"]="0:0:0755"

  # ── YantraOS secrets directory ─────────────────────────────────────────────
  # Root-owned, yantra-group-readable. No world access.
  ["/etc/yantra"]="0:0:0750"
)
