#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# forge_sovereign_iso.sh — YantraOS RC3 Sovereign ISO Forge
#
# A single, idempotent, brutalist build monolith that consolidates the legacy
# trio (build.sh + archlive/compile_iso.sh + make_yantra_iso.sh) into one
# auditable pipeline:
#
#   verify_dependencies → scaffold_airootfs → inject_kriya_loop
#                       → compile_iso → sign_artifact
#
# DESIGN PRINCIPLES
#   • Ephemeral by construction: the profile is assembled in a scratch dir
#     (mktemp), never mutating the repo's archlive/ source of truth.
#   • Hashbang-correct by construction: the Python venv is created INSIDE an
#     arch-chroot of the airootfs, so every shebang is born as the TARGET path
#     (/opt/yantra/venv/bin/python3) — no fragile post-hoc sed surgery.
#   • Fail-closed: the signing key is verified BEFORE any compute is spent.
#   • Secret-clean: application credentials never enter the build. The signing
#     key stays on the forge host and its temporary GNUPGHOME is destroyed.
#
# USAGE
#   export YANTRA_SIGNING_KEY=/path/to/yantra-ed25519-private.key
#   sudo -E ./forge_sovereign_iso.sh
#
# HOST REQUIREMENTS
#   Bare-metal Arch Linux, UID 0, with: archiso, btrfs-progs, squashfs-tools,
#   arch-install-scripts (pacstrap/arch-chroot), python, rsync, gnupg.
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
IFS=$'\n\t'

# ── Static geometry ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
readonly SCRIPT_DIR

readonly RELENG_SRC="/usr/share/archiso/configs/releng"     # baseline Arch profile
readonly PROFILE_SRC="${SCRIPT_DIR}"                        # YantraOS profile overlay
readonly WORK_DIR="/tmp/yantra-work"                        # mkarchiso scratch (tmpfs)
readonly OUT_DIR="/opt/yantra-releases"                     # immutable artifact sink
readonly VENV_TARGET="/opt/yantra/venv"                     # venv path on the LIVE ISO
readonly SANDBOX_IMAGE="yantra-sandbox:3.20.3"
readonly SANDBOX_ARCHIVE="/opt/yantra/images/yantra-sandbox-3.20.3.tar"

# Signing key supplied strictly via the environment — never substituted in-script.
readonly SIGNING_KEY="${YANTRA_SIGNING_KEY:-}"
readonly SIGNING_KEY_PASSPHRASE="${YANTRA_SIGNING_KEY_PASSPHRASE:-}"

# Dependency command → providing package, for actionable pre-flight errors.
readonly -A REQUIRED_PKGS=(
  [mkarchiso]="archiso"
  [mksquashfs]="squashfs-tools"
  [mkfs.btrfs]="btrfs-progs"
  [pacstrap]="arch-install-scripts"
  [arch-chroot]="arch-install-scripts"
  [rsync]="rsync"
  [gpg]="gnupg"
  [docker]="docker"
)

# Systemd units symlinked into multi-user.target.wants on the live node.
readonly -a BASE_SERVICES=(
  "docker.service" "systemd-networkd.service"
  "systemd-resolved.service" "iwd.service" "ufw.service"
)
# Custom YantraOS units (live in /etc/systemd/system, staged from deploy/systemd).
readonly -a YANTRA_SERVICES=(
  "yantra-provision-secrets.service" "yantra-sandbox-broker.service"
  "yantra.service"
)

# Mutable globals populated at runtime.
BUILD_PROFILE=""    # ephemeral assembled-profile dir (mktemp)
AIROOTFS=""         # ${BUILD_PROFILE}/airootfs
VENV_BUILD_DIR=""   # ephemeral venv-compilation chroot (/tmp/yantra-venv-chroot-$$)

# ── Logging ───────────────────────────────────────────────────────────────────
readonly C_RED='\033[0;31m' C_GRN='\033[0;32m' C_YEL='\033[1;33m' C_CYN='\033[0;36m' C_NC='\033[0m'
log_info() { echo -e "${C_CYN}[INFO]${C_NC} $*"; }
log_ok()   { echo -e "${C_GRN}[ OK ]${C_NC} $*"; }
log_warn() { echo -e "${C_YEL}[WARN]${C_NC} $*" >&2; }
log_fatal(){ echo -e "${C_RED}[FATAL]${C_NC} $*" >&2; }
die()      { log_fatal "$*"; exit 1; }

# ── Lifecycle cleanup ─────────────────────────────────────────────────────────
# Always reclaim the ephemeral profile + work scratch, even on failure. The
# arch-chroot helper auto-unmounts its api mounts on exit, but we belt-and-
# suspenders any stray binds under the airootfs before removal.
cleanup() {
  local rc=$?
  # Lazy-unmount any lingering api filesystems from an aborted chroot, for both
  # the staging airootfs and the ephemeral venv-build matrix.
  local root mp
  for root in "${AIROOTFS}" "${VENV_BUILD_DIR}"; do
    [[ -n "${root}" && -d "${root}" ]] || continue
    for mp in proc sys dev/pts dev run; do
      mountpoint -q "${root}/${mp}" 2>/dev/null && umount -lf "${root}/${mp}" 2>/dev/null || true
    done
  done
  # Absolute destruction of the venv matrix — never let it survive a crash and
  # exhaust CI/CD host capacity (constraint §4). obliterate_venv_matrix is the
  # explicit success path; this is the trap safety net.
  [[ -n "${VENV_BUILD_DIR}" && -d "${VENV_BUILD_DIR}" ]] && rm -rf -- "${VENV_BUILD_DIR}" || true
  [[ -n "${BUILD_PROFILE}" && -d "${BUILD_PROFILE}" ]] && rm -rf -- "${BUILD_PROFILE}" || true
  [[ -d "${WORK_DIR}" ]] && rm -rf -- "${WORK_DIR}" || true
  return $rc
}
trap cleanup EXIT

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — verify_dependencies
#   Fail closed before spending a single CPU cycle on compilation.
# ══════════════════════════════════════════════════════════════════════════════
verify_dependencies() {
  log_info "═══ verify_dependencies ═══"

  # 1.1 — Root. mkarchiso/pacstrap/arch-chroot all require UID 0.
  [[ "${EUID}" -eq 0 ]] || die "Must run as root (UID 0). Re-run: sudo -E $0"
  log_ok "Root privileges confirmed (EUID=0)."

  # 1.2 — Signing key MUST exist up front (fail-closed sealing contract).
  [[ -n "${SIGNING_KEY}" ]] \
    || die "YANTRA_SIGNING_KEY is unset. Export the Ed25519 key path before forging."
  [[ -f "${SIGNING_KEY}" && -r "${SIGNING_KEY}" ]] \
    || die "YANTRA_SIGNING_KEY is not a readable file: ${SIGNING_KEY}"
  log_ok "Signing key present: ${SIGNING_KEY}"

  # 1.3 — Toolchain. archiso, btrfs-progs, squashfs-tools, + chroot/rsync/gpg.
  local missing=() cmd pkg
  for cmd in "${!REQUIRED_PKGS[@]}"; do
    pkg="${REQUIRED_PKGS[$cmd]}"
    command -v "${cmd}" >/dev/null 2>&1 || missing+=("${pkg} (provides '${cmd}')")
  done
  if (( ${#missing[@]} > 0 )); then
    printf '  - %s\n' "${missing[@]}" >&2
    die "Missing dependencies. Install: pacman -S --needed archiso btrfs-progs squashfs-tools arch-install-scripts rsync gnupg"
  fi
  log_ok "All build dependencies satisfied."

  # 1.4 — Source profile sanity.
  [[ -d "${RELENG_SRC}" ]]   || die "Baseline releng profile not found: ${RELENG_SRC} (install 'archiso')."
  [[ -d "${PROFILE_SRC}" ]]  || die "YantraOS profile overlay not found: ${PROFILE_SRC}"
  [[ -f "${PROFILE_SRC}/profiledef.sh" ]] || die "Missing profiledef.sh in ${PROFILE_SRC}"
  local source_dir
  for source_dir in core scripts deploy; do
    [[ -d "${SCRIPT_DIR}/../${source_dir}" ]] \
      || die "Required source directory missing: ${SCRIPT_DIR}/../${source_dir}"
  done
  [[ -f "${SCRIPT_DIR}/../requirements.txt" ]] \
    || die "Required dependency manifest missing: ${SCRIPT_DIR}/../requirements.txt"
  [[ -f "${SCRIPT_DIR}/../requirements.lock" ]] \
    || die "Required dependency lock missing: ${SCRIPT_DIR}/../requirements.lock"
  log_ok "Profile sources verified (releng baseline + YantraOS overlay)."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — scaffold_airootfs
#   Assemble the ephemeral profile: releng baseline → YantraOS overlay →
#   fresh codebase rsync → systemd wire-up → identity/fs scaffold.
# ══════════════════════════════════════════════════════════════════════════════
scaffold_airootfs() {
  log_info "═══ scaffold_airootfs ═══"

  # 2.1 — Ephemeral profile dir on tmpfs-ish scratch.
  BUILD_PROFILE="$(mktemp -d /tmp/yantra-forge.XXXXXXXX)"
  AIROOTFS="${BUILD_PROFILE}/airootfs"
  log_info "Ephemeral profile: ${BUILD_PROFILE}"

  # 2.2 — Layer 0: baseline Arch releng profile.
  cp -a -- "${RELENG_SRC}/." "${BUILD_PROFILE}/"
  log_ok "Copied releng baseline."

  # 2.3 — Layer 1: YantraOS overlay (profiledef, pacman.conf, packages, custom
  #         airootfs units/hooks/branding). Excludes build artifacts + the
  #         retired legacy compile script so they never enter the profile.
  rsync -a \
    --exclude 'out/' --exclude 'work/' --exclude 'compile_iso.sh' \
    "${PROFILE_SRC}/" "${BUILD_PROFILE}/"
  # The releng baseline enables local autologin; YantraOS requires authentication.
  if [[ -d "${AIROOTFS}/etc/systemd/system" ]]; then
    find "${AIROOTFS}/etc/systemd/system" -path '*getty*' -name 'autologin.conf' -delete
  fi
  log_ok "Overlaid YantraOS profile customizations."

  # 2.4 — Layer 2: inject the live codebase into airootfs/opt/yantra/.
  #         Amnesia Protocol: no secrets, host state, or bytecode in the ISO.
  local dest="${AIROOTFS}/opt/yantra"
  install -dm755 "${dest}"
  local sub src
  for sub in core scripts deploy; do
    src="${SCRIPT_DIR}/../${sub}"
    [[ -d "${src}" ]] || die "Required source directory missing: ${src}"
    rsync -a --chown=root:root --delete \
      --exclude='.env*' --exclude='*.pem' --exclude='*.key' \
      --exclude='*.db' --exclude='*.sqlite*' \
      --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.json' \
      "${src}/" "${dest}/${sub}/"
    log_info "  ↳ rsynced ${sub}/ → /opt/yantra/${sub}/"
  done
  # requirements.txt rides along so the in-chroot pip pass can resolve extras.
  [[ -f "${SCRIPT_DIR}/../requirements.txt" ]] \
    || die "Required dependency manifest missing: ${SCRIPT_DIR}/../requirements.txt"
  install -Dm644 "${SCRIPT_DIR}/../requirements.txt" "${dest}/requirements.txt"
  install -Dm644 "${SCRIPT_DIR}/../requirements.lock" "${dest}/requirements.lock"
  log_ok "Codebase injected into airootfs/opt/yantra/."

  stage_sandbox_image
  wire_systemd
  scaffold_identity_and_fs
  provision_global_binaries
}

stage_sandbox_image() {
  log_info "── stage_sandbox_image ──"
  local archive="${AIROOTFS}${SANDBOX_ARCHIVE}"
  install -dm755 "$(dirname -- "${archive}")"
  docker build --pull --tag "${SANDBOX_IMAGE}" "${SCRIPT_DIR}/../core/sandbox"
  docker image inspect "${SANDBOX_IMAGE}" >/dev/null
  docker save --output "${archive}" "${SANDBOX_IMAGE}"
  chmod 0644 "${archive}"
  log_ok "Pinned sandbox image staged at ${SANDBOX_ARCHIVE}."
}

# ── 2.x — Global binary wrappers ──────────────────────────────────────────────
# Provision system-wide executable wrappers in /usr/bin/ so the Host Executor
# and pacman hooks can locate YantraOS tools without knowing the venv path.
provision_global_binaries() {
  log_info "── provision_global_binaries ──"

  # /usr/bin/yantra-snapshot → venv python3 cli_snapshot.py
  local snap_bin="${AIROOTFS}/usr/bin/yantra-snapshot"
  install -dm755 "$(dirname -- "${snap_bin}")"
  cat > "${snap_bin}" <<'SNAPEOF'
#!/bin/bash
# YantraOS — Global BTRFS Snapshot Wrapper
# Delegates to the venv-isolated CLI so the Host Executor and pacman hooks
# can call a single, PATH-resolvable binary without venv activation.
exec /opt/yantra/venv/bin/python3 /opt/yantra/core/cli_snapshot.py "$@"
SNAPEOF
  chmod 0755 "${snap_bin}"
  log_ok "/usr/bin/yantra-snapshot wrapper provisioned."
}

# ── 2.x — Systemd symlink matrix ──────────────────────────────────────────────
# multi-user.target.wants is rebuilt from truth: nuke stale entries (Windows-
# scaffolded "symlinks" are often regular files), then recreate proper links.
wire_systemd() {
  log_info "── wire_systemd ──"
  local wants="${AIROOTFS}/etc/systemd/system/multi-user.target.wants"
  install -dm755 "${wants}"
  rm -f -- "${wants}"/*

  # Distro units shipped by their packages (target under /usr/lib).
  local unit
  for unit in "${BASE_SERVICES[@]}"; do
    ln -sf "/usr/lib/systemd/system/${unit}" "${wants}/${unit}"
    log_info "  ↳ ${unit}"
  done

  # Custom YantraOS units: stage the unit file from deploy/systemd, then enable.
  local sysd="${AIROOTFS}/etc/systemd/system"
  install -dm755 "${sysd}"
  for unit in "${YANTRA_SERVICES[@]}"; do
    local src="${SCRIPT_DIR}/../deploy/systemd/${unit}"
    [[ -f "${src}" ]] || die "Required unit file missing: ${src}"
    install -Dm644 "${src}" "${sysd}/${unit}"
    ln -sf "/etc/systemd/system/${unit}" "${wants}/${unit}"
    log_info "  ↳ ${unit} (local unit)"
  done
  install -Dm644 "${SCRIPT_DIR}/../deploy/sysusers.d/yantra.conf" \
    "${AIROOTFS}/usr/lib/sysusers.d/yantra.conf"
  install -Dm644 "${SCRIPT_DIR}/../deploy/tmpfiles.d/yantra.conf" \
    "${AIROOTFS}/usr/lib/tmpfiles.d/yantra.conf"
  # /etc/yantra/secrets.env is intentionally absent. Provision it root:root
  # 0600 after boot, then restart the services that consume it.
  log_ok "Systemd matrix wired: ${#BASE_SERVICES[@]} base + ${#YANTRA_SERVICES[@]} YantraOS units."
}

# ── 2.x — Identity + filesystem scaffold ──────────────────────────────────────
# Load-bearing: without /var/lib/yantra, yantra.service namespace setup panics
# with status=226/NAMESPACE before the binary runs.
scaffold_identity_and_fs() {
  log_info "── scaffold_identity_and_fs ──"

  # Lock root. The ISO has neither local user login nor autologin.
  install -dm755 "${AIROOTFS}/etc"
  printf 'root:!:14871::::::\n' > "${AIROOTFS}/etc/shadow"
  chmod 0400 "${AIROOTFS}/etc/shadow"

  # Persistent state dirs are assigned by systemd-tmpfiles after sysusers runs.
  install -dm750 "${AIROOTFS}/var/lib/yantra" "${AIROOTFS}/var/log/yantra"

  # ── Oneshot live-setup unit ──────────────────────────────────────────────
  # BTRFS nodatacow + hook unmask, ordered Before the daemon, so first boot
  # doesn't crash on a missing chromadb directory.
  local setup="${AIROOTFS}/etc/systemd/system/yantra-live-setup.service"
  cat > "${setup}" <<'SVCEOF'
[Unit]
Description=YantraOS Live Environment Setup
DefaultDependencies=no
Before=yantra.service
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c "mkdir -p /var/lib/yantra/chromadb && chattr +C /var/lib/yantra/chromadb 2>/dev/null || true"
ExecStart=/bin/bash -c "chown yantra_daemon:yantra /var/lib/yantra/chromadb 2>/dev/null || true"
ExecStart=/bin/bash -c "chmod 750 /var/lib/yantra/chromadb"
ExecStart=/bin/bash -c "if [ -f /etc/pacman.d/hooks/00-yantra-autosnap.hook.inactive ]; then mv /etc/pacman.d/hooks/00-yantra-autosnap.hook.inactive /etc/pacman.d/hooks/00-yantra-autosnap.hook; fi"

[Install]
WantedBy=multi-user.target
SVCEOF
  chmod 644 "${setup}"
  ln -sf "/etc/systemd/system/yantra-live-setup.service" \
    "${AIROOTFS}/etc/systemd/system/multi-user.target.wants/yantra-live-setup.service"
  log_ok "Identity + filesystem scaffold complete."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — inject_kriya_loop
#   Compile the Python execution matrix inside a STRICTLY EPHEMERAL pacstrap
#   chroot (never the airootfs overlay), then inject ONLY the pristine venv tree
#   into the staging airootfs. The build matrix is obliterated the instant the
#   rsync succeeds. Building the venv at its final path (/opt/yantra/venv) makes
#   every shebang born as the TARGET path. Version-skew is eliminated by
#   construction: the matrix and ISO resolve python from the same Arch core repo
#   (pin further via YANTRA_PYTHON_PIN, e.g. "python=3.12.7").
# ══════════════════════════════════════════════════════════════════════════════
inject_kriya_loop() {
  log_info "═══ inject_kriya_loop ═══"

  # 3.1 — Guarantee the interpreter + sandbox packages are in the ISO manifest.
  #         The ISO's runtime python is installed by mkarchiso from this list;
  #         the venv's interpreter symlink resolves against it at boot.
  ensure_packages python python-pip rsync docker bubblewrap

  # 3.2 — Define + create the ephemeral build matrix. Registered in the global
  #         so the EXIT trap can obliterate it even on a crash (constraint §4).
  VENV_BUILD_DIR="/tmp/yantra-venv-chroot-$$"
  rm -rf -- "${VENV_BUILD_DIR}"
  install -dm755 "${VENV_BUILD_DIR}"
  log_info "Ephemeral venv matrix: ${VENV_BUILD_DIR}"

  # 3.3 — Minimal pacstrap into the throwaway matrix (NOT the airootfs).
  #         Optional explicit version pin via YANTRA_PYTHON_PIN closes any skew window.
  local -a venv_pkgs=(base python python-pip python-virtualenv)
  if [[ -n "${YANTRA_PYTHON_PIN:-}" ]]; then
    # Replace ONLY the standalone 'python' atom — never python-pip/-virtualenv.
    local i
    for i in "${!venv_pkgs[@]}"; do
      [[ "${venv_pkgs[$i]}" == "python" ]] && venv_pkgs[$i]="${YANTRA_PYTHON_PIN}"
    done
  fi
  log_info "Pacstrapping minimal matrix: ${venv_pkgs[*]}"
  pacstrap -c "${VENV_BUILD_DIR}" "${venv_pkgs[@]}" >/dev/null

  # 3.4 — DNS for in-chroot pip; stage requirements.txt INTO the matrix.
  install -Dm644 /etc/resolv.conf "${VENV_BUILD_DIR}/etc/resolv.conf" 2>/dev/null || true
  install -Dm644 "${SCRIPT_DIR}/../requirements.lock" "${VENV_BUILD_DIR}/opt/yantra/requirements.lock"

  # 3.5 — Isolated compilation: build the venv at /opt/yantra/venv inside the
  #         matrix. Quoted heredoc → all paths are owned by the chroot.
  log_info "Compiling venv + Kriya Loop dependencies (isolated arch-chroot)..."
  env -u YANTRA_SIGNING_KEY -u YANTRA_SIGNING_KEY_PASSPHRASE \
    arch-chroot "${VENV_BUILD_DIR}" /bin/bash -s <<'CHROOT'
set -euo pipefail

# ── Network Hardening: Force HTTP/1.1 + expand Git buffer ────────────────
# Default Git/cURL HTTP/2 negotiation collapses inside ephemeral chroot
# overlays during large VCS clones (pip git+ dependencies). Force HTTP/1.1
# and expand the postBuffer to 500MB to prevent stream reset errors.
export GIT_HTTP_VERSION=1.1
git config --system http.postBuffer 524288000

VENV=/opt/yantra/venv
install -dm755 /opt/yantra
python -m venv "${VENV}"
"${VENV}/bin/pip" install --require-hashes -r /opt/yantra/requirements.lock --prefer-binary --quiet --retries 10 --timeout 120
CHROOT
  log_ok "Venv compiled in ephemeral matrix."

  # 3.6 — Pristine injection: sync ONLY the venv tree into the staging airootfs,
  #         forced root-owned. (Destination is ${AIROOTFS} — the profile's
  #         airootfs — not mkarchiso's ${WORK_DIR}, which does not exist yet.)
  local matrix_venv="${VENV_BUILD_DIR}${VENV_TARGET}"
  local venv_dest="${AIROOTFS}${VENV_TARGET}"
  [[ -d "${matrix_venv}" ]] || die "Compilation produced no venv at ${matrix_venv}."
  install -dm755 "$(dirname -- "${venv_dest}")"
  rm -rf -- "${venv_dest}"
  rsync -a --chown=root:root "${matrix_venv}/" "${venv_dest}/"
  log_ok "Pristine venv injected → airootfs${VENV_TARGET}"

  # 3.7 — Absolute destruction of the matrix immediately upon a successful sync
  #         (don't wait for the trap; free disk now — constraint §4).
  obliterate_venv_matrix

  # 3.8 — Verify a representative shebang points at the TARGET path.
  local probe="${venv_dest}/bin/pip"
  if [[ -f "${probe}" ]]; then
    head -1 "${probe}" | grep -q "${VENV_TARGET}" \
      && log_ok "Hashbang verification passed: $(head -1 "${probe}")" \
      || die "Hashbang verification FAILED: $(head -1 "${probe}")"
  fi

  sanitize_airootfs
}

# ── Obliterate the ephemeral venv matrix (unmount api binds, then shred dir). ──
# Idempotent: safe to call from the success path AND the EXIT trap.
obliterate_venv_matrix() {
  [[ -n "${VENV_BUILD_DIR}" && -d "${VENV_BUILD_DIR}" ]] || return 0
  local mp
  for mp in proc sys dev/pts dev run; do
    mountpoint -q "${VENV_BUILD_DIR}/${mp}" 2>/dev/null && umount -lf "${VENV_BUILD_DIR}/${mp}" 2>/dev/null || true
  done
  rm -rf -- "${VENV_BUILD_DIR}"
  log_ok "Ephemeral venv matrix obliterated: ${VENV_BUILD_DIR}"
  VENV_BUILD_DIR=""   # disarm the trap; already destroyed
}

# ── Append a package to the ISO manifest iff not already present. ─────────────
ensure_packages() {
  local pkg_file="${BUILD_PROFILE}/packages.x86_64"
  [[ -f "${pkg_file}" ]] || die "packages.x86_64 missing in assembled profile."
  local pkg
  for pkg in "$@"; do
    grep -qx "${pkg}" "${pkg_file}" || { echo "${pkg}" >> "${pkg_file}"; log_info "  ↳ +pkg ${pkg}"; }
  done
}

# ── Amnesia Protocol + CRLF sanitation ────────────────────────────────────────
# Purge host state + Windows line endings that would silently break units.
sanitize_airootfs() {
  log_info "── sanitize_airootfs ──"
  # Drop transient host state + bytecode. The venv is now compiled in a separate
  # ephemeral matrix (see inject_kriya_loop) and only the pristine venv tree is
  # injected — so NO bootstrap pacman cache/DB residue lands in the overlay and
  # nothing here needs to purge it. resolv.conf is staged into the matrix, not
  # the airootfs; this removal is a cheap defensive no-op against stray copies.
  rm -f -- "${AIROOTFS}/etc/resolv.conf" 2>/dev/null || true
  find "${AIROOTFS}/opt/yantra/" -not -path '*/venv/*' \( -name '*.json' -o -name '*.pyc' \) -type f -delete 2>/dev/null || true
  find "${AIROOTFS}/opt/yantra/" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  rm -rf -- "${AIROOTFS}/var/lib/yantra/chromadb" "${AIROOTFS}/var/lib/yantra/chroma" 2>/dev/null || true

  # CRLF → LF on text config/scripts (skip the venv binaries).
  local count=0 file
  while IFS= read -r -d '' file; do
    if file "${file}" 2>/dev/null | grep -q "text" && grep -qU $'\r' "${file}" 2>/dev/null; then
      sed -i 's/\r$//' "${file}"; count=$((count + 1))
    fi
  done < <(find "${BUILD_PROFILE}" -path "${AIROOTFS}${VENV_TARGET}" -prune -o -type f \( \
      -name '*.sh' -o -name '*.py' -o -name '*.conf' -o -name '*.service' \
      -o -name '*.hook' -o -name '*.rules' -o -name '*.env' -o -name '*.network' \
      -o -name 'profiledef.sh' -o -name 'packages.x86_64' -o -name 'pacman.conf' \
    \) -print0)
  log_ok "Amnesia + CRLF sanitation complete (${count} file(s) normalized)."

  # mkarchiso maps build-tree UIDs into the squashfs — enforce root:root so no
  # stray ownership cascades into the immutable image. root:root is the correct
  # default for the venv (tmpfiles.d pins /opt/yantra/venv 0755 root:root) and
  # for all profile metadata.
  chown -R root:root "${BUILD_PROFILE}"

  log_ok "Ownership audit: profile root:root; runtime owners derive from sysusers."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — compile_iso
#   The canonical archiso invocation against the assembled ephemeral profile.
# ══════════════════════════════════════════════════════════════════════════════
compile_iso() {
  log_info "═══ compile_iso ═══"
  rm -rf -- "${WORK_DIR}"
  install -dm755 "${WORK_DIR}" "${OUT_DIR}"

  log_info "mkarchiso → profile=${BUILD_PROFILE} work=${WORK_DIR} out=${OUT_DIR}"
  mkarchiso -v -w "${WORK_DIR}" -o "${OUT_DIR}" "${BUILD_PROFILE}"

  rm -rf -- "${WORK_DIR}"
  log_ok "mkarchiso completed. Artifacts in ${OUT_DIR}."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5 — sign_artifact
#   SHA-256 the freshly built ISO, then sign the checksum with the Ed25519 key
#   inside an EPHEMERAL GNUPGHOME that is shredded the instant signing finishes.
# ══════════════════════════════════════════════════════════════════════════════
sign_artifact() {
  log_info "═══ sign_artifact ═══"

  # Resolve the just-built ISO (newest .iso in the output sink).
  local iso_path
  iso_path="$(find "${OUT_DIR}" -maxdepth 1 -type f -name '*.iso' -printf '%T@ %p\n' \
    | sort -nr | head -n1 | cut -d' ' -f2-)"
  [[ -n "${iso_path}" && -f "${iso_path}" ]] || die "No .iso found in ${OUT_DIR} — compilation failed."
  local iso_name; iso_name="$(basename -- "${iso_path}")"

  # Deterministic SHA-256 (sha256sum -c compatible), then self-verify.
  log_info "Hashing → ${iso_name}.sha256"
  ( cd -- "${OUT_DIR}" && sha256sum -- "${iso_name}" > "${iso_name}.sha256" )
  ( cd -- "${OUT_DIR}" && sha256sum -c -- "${iso_name}.sha256" >/dev/null ) \
    || die "Checksum self-verification failed for ${iso_name}."
  local sum_file="${OUT_DIR}/${iso_name}.sha256"

  # Ephemeral, isolated keyring — host keyring is never touched.
  local gnupg_tmp; gnupg_tmp="$(mktemp -d /tmp/yantra-gnupg.XXXXXXXX)"
  chmod 700 -- "${gnupg_tmp}"

  log_info "Signing checksum with Ed25519 key (ephemeral GNUPGHOME)..."
  GNUPGHOME="${gnupg_tmp}" gpg --batch --quiet --import -- "${SIGNING_KEY}" \
    || { wipe_gnupghome "${gnupg_tmp}"; die "Failed to import signing key."; }

  local -a sign_cmd=(gpg --batch --yes --armor --trust-model always --detach-sign)
  [[ -n "${SIGNING_KEY_PASSPHRASE}" ]] && sign_cmd+=(--pinentry-mode loopback --passphrase-fd 0)
  sign_cmd+=(--output "${sum_file}.sig" -- "${sum_file}")

  rm -f -- "${sum_file}.sig"
  if [[ -n "${SIGNING_KEY_PASSPHRASE}" ]]; then
    GNUPGHOME="${gnupg_tmp}" "${sign_cmd[@]}" <<<"${SIGNING_KEY_PASSPHRASE}" || {
      wipe_gnupghome "${gnupg_tmp}"
      die "GPG signing of checksum failed."
    }
  elif ! GNUPGHOME="${gnupg_tmp}" "${sign_cmd[@]}"; then
    wipe_gnupghome "${gnupg_tmp}"
    die "GPG signing of checksum failed."
  fi

  GNUPGHOME="${gnupg_tmp}" gpg --batch --verify -- "${sum_file}.sig" "${sum_file}" >/dev/null 2>&1 \
    && log_ok "Signature verified against imported key." \
    || { wipe_gnupghome "${gnupg_tmp}"; die "Signature verification failed."; }

  # Shred + wipe the keyring IMMEDIATELY upon signature generation.
  wipe_gnupghome "${gnupg_tmp}"
  log_ok "GNUPGHOME shredded. Sealed: ${iso_name}{,.sha256,.sha256.sig}"
}

# ── Securely destroy an ephemeral GNUPGHOME ───────────────────────────────────
wipe_gnupghome() {
  local home="$1"
  [[ -n "${home}" && -d "${home}" ]] || return 0
  if command -v shred >/dev/null 2>&1; then
    find "${home}" -type f -exec shred -uz {} + 2>/dev/null || true
  fi
  rm -rf -- "${home}"
}

# ══════════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════════
main() {
  log_info "════════════════════════════════════════════════════════════════"
  log_info "  YantraOS Sovereign ISO Forge"
  log_info "════════════════════════════════════════════════════════════════"
  verify_dependencies
  scaffold_airootfs
  inject_kriya_loop
  compile_iso
  sign_artifact
  log_ok "Forge complete. Signed artifacts in ${OUT_DIR}."
}

main "$@"
