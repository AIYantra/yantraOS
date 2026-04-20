#!/usr/bin/env bash
# shellcheck disable=SC2034
# ──────────────────────────────────────────────────────────────────────────────
# YantraOS Phase 6 — Gold Master ISO Profile Definition
# Target: archlive/profiledef.sh
# ──────────────────────────────────────────────────────────────────────────────

iso_name="yantraos"
iso_label="YANTRA_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="YantraOS Project <https://yantraos.com>"
iso_application="YantraOS — Level 3 AI-Agent Operating System"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="yantra"
buildmodes=('iso')
bootmodes=('bios.syslinux.mbr' 'bios.syslinux.eltorito'
           'uefi-x64.grub.esp' 'uefi-x64.grub.eltorito')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'xz' '-Xbcj' 'x86' '-b' '1M' '-Xdict-size' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')

file_permissions=(
  ["/etc/shadow"]="0:0:0400"
  ["/etc/gshadow"]="0:0:0400"
  ["/etc/initcpio/install/yantra-origin"]="0:0:0755"
  ["/etc/initcpio/hooks/yantra-origin"]="0:0:0755"
  ["/etc/yantra/host_secrets.env"]="0:0:0600"
  ["/etc/yantra/secrets.env"]="0:0:0600"
  ["/root"]="0:0:0750"
  ["/root/.automated_script.sh"]="0:0:0755"
  ["/root/.gnupg"]="0:0:0700"
  ["/opt/yantra/core/tui_shell.py"]="0:0:0755"
  ["/opt/yantra/core/daemon.py"]="0:0:0755"
)
