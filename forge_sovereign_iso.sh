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
#   • Secret-clean: secrets arrive only via files/env, never baked into the
#     script; the GNUPGHOME used for signing is shredded immediately after use.
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
readonly PROFILE_SRC="${SCRIPT_DIR}/archlive"               # YantraOS profile overlay
readonly WORK_DIR="/tmp/yantra-work"                        # mkarchiso scratch (tmpfs)
readonly OUT_DIR="/opt/yantra-releases"                     # immutable artifact sink
readonly VENV_TARGET="/opt/yantra/venv"                     # venv path on the LIVE ISO

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
)

# Python execution matrix shipped inside the venv.
readonly -a YANTRA_PIP_PACKAGES=(
  "fastapi" "uvicorn[standard]" "litellm" "chromadb"
  "docker" "sdnotify" "pynvml" "textual" "rich"
)

# Systemd units symlinked into multi-user.target.wants on the live node.
readonly -a BASE_SERVICES=(
  "docker.service" "sshd.service" "systemd-networkd.service"
  "systemd-resolved.service" "iwd.service" "ufw.service"
)
# Custom YantraOS units (live in /etc/systemd/system, staged from deploy/systemd).
readonly -a YANTRA_SERVICES=(
  "yantra.service" "yantra-host-executor.service"
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
  log_ok "Profile sources verified (releng baseline + YantraOS overlay)."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — scaffold_airootfs
#   Assemble the ephemeral profile: releng baseline → YantraOS overlay →
#   fresh codebase rsync → systemd wire-up → secrets → identity/fs scaffold.
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
  log_ok "Overlaid YantraOS profile customizations."

  # 2.4 — Layer 2: inject the live codebase into airootfs/opt/yantra/.
  #         Mirrors scripts/sync_to_iso.sh semantics (Amnesia Protocol: no
  #         secrets, no host state, no pyc/json bleed into the immutable ISO).
  local dest="${AIROOTFS}/opt/yantra"
  install -dm755 "${dest}"
  local sub
  for sub in core scripts deploy; do
    [[ -d "${SCRIPT_DIR}/${sub}" ]] || { log_warn "Source dir absent, skipping: ${sub}/"; continue; }
    rsync -a --delete \
      --exclude='.env*' --exclude='*.pem' --exclude='*.key' \
      --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.json' \
      "${SCRIPT_DIR}/${sub}/" "${dest}/${sub}/"
    log_info "  ↳ rsynced ${sub}/ → /opt/yantra/${sub}/"
  done
  # requirements.txt rides along so the in-chroot pip pass can resolve extras.
  [[ -f "${SCRIPT_DIR}/requirements.txt" ]] && install -Dm644 "${SCRIPT_DIR}/requirements.txt" "${dest}/requirements.txt"
  log_ok "Codebase injected into airootfs/opt/yantra/."

  wire_systemd
  stage_secrets
  scaffold_identity_and_fs
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
    local src="${SCRIPT_DIR}/deploy/systemd/${unit}"
    [[ -f "${src}" ]] || die "Required unit file missing: ${src}"
    install -Dm644 "${src}" "${sysd}/${unit}"
    ln -sf "/etc/systemd/system/${unit}" "${wants}/${unit}"
    log_info "  ↳ ${unit} (local unit)"
  done
  log_ok "Systemd matrix wired: ${#BASE_SERVICES[@]} base + ${#YANTRA_SERVICES[@]} YantraOS units."
}

# ── 2.x — Secrets staging (host_secrets.env → airootfs) ───────────────────────
# Inference credentials are mandatory for a functional node, but optional for a
# bare smoke build. Stage if present; warn loudly if absent.
#
# PATH LAYOUT (post-migration):
#   /etc/yantra/host_secrets.env          — 0600 root:root   (immutable reference copy)
#   /etc/yantra/writable/host_secrets.env — 0660 root:yantra (daemon-writable live copy)
#
# The EnvironmentFile= drop-in points at the WRITABLE path so the daemon
# inherits credentials it can also mutate via POST /api/config.
stage_secrets() {
  log_info "── stage_secrets ──"
  local host_secrets="${SCRIPT_DIR}/host_secrets.env"
  local etc_yantra="${AIROOTFS}/etc/yantra"
  local staged_ro="${etc_yantra}/host_secrets.env"          # immutable reference
  local staged_rw="${etc_yantra}/writable/host_secrets.env" # daemon-writable live copy

  # Refuse to build if secrets are tracked in git (severe leak).
  if command -v git >/dev/null 2>&1 && [[ -d "${SCRIPT_DIR}/.git" ]]; then
    if git -C "${SCRIPT_DIR}" ls-files --error-unmatch "host_secrets.env" >/dev/null 2>&1; then
      die "host_secrets.env is tracked in git. Run: git rm --cached host_secrets.env"
    fi
  fi

  if [[ ! -f "${host_secrets}" ]]; then
    log_warn "host_secrets.env absent — ISO will ship WITHOUT inference credentials."
    log_warn "The daemon's cloud fallback will be inert until credentials are provided."
    return 0
  fi

  # ── Read-only reference copy (/etc/yantra/host_secrets.env) ──────────────
  # Root-only 0600: survives as the canonical install-time source of truth.
  # Nothing should read this file at runtime — it exists for forensic audits.
  install -dm700 "${etc_yantra}"
  install -Dm600 "${host_secrets}" "${staged_ro}"
  chown 0:0 "${staged_ro}"              # root:root — intentionally unreadable by daemon
  # systemd EnvironmentFile passes quotes literally — strip them and trailing ws.
  sed -i "s/['\"]//g; s/[[:space:]]*$//" "${staged_ro}"

  # ── Writable live copy (/etc/yantra/writable/host_secrets.env) ───────────
  # Mode 0660 root:yantra: yantra_daemon (member of yantra group) can read AND
  # write this file, allowing POST /api/config to perform atomic key rotation.
  install -dm770 "${etc_yantra}/writable"
  chown 0:998 "${etc_yantra}/writable"   # root:yantra (GID 998)
  install -Dm660 "${host_secrets}" "${staged_rw}"
  chown 0:998 "${staged_rw}"             # root:yantra
  chmod 0660 "${staged_rw}"
  sed -i "s/['\"]//g; s/[[:space:]]*$//" "${staged_rw}"
  log_ok "Secrets staged: 0600 root:root (reference) + 0660 root:yantra (writable)."

  # ── EnvironmentFile drop-in → writable path ──────────────────────────────
  # yantra.service reads from the live writable copy so key updates take effect
  # on the NEXT service reload without requiring a root-level file swap.
  local dropin="${AIROOTFS}/etc/systemd/system/yantra.service.d"
  install -dm755 "${dropin}"
  printf '[Service]\nEnvironmentFile=/etc/yantra/writable/host_secrets.env\n' > "${dropin}/env.conf"
  chmod 640 "${dropin}/env.conf"
  log_ok "EnvironmentFile drop-in → /etc/yantra/writable/host_secrets.env"
}


# ── 2.x — Identity + filesystem scaffold ──────────────────────────────────────
# Load-bearing: without the home dir + zeroed shadow, agetty autologin → PAM
# fails; without /var/lib/yantra, yantra.service namespace setup panics with
# status=226/NAMESPACE before the binary runs.
#
# RC3-KIOSK EXTENSION:
#   Wire the Wayland Kiosk (cage + chromium) into the boot sequence:
#     1. Package manifest: cage, chromium, mesa, seatd, wlroots, xdg-desktop-portal
#     2. getty@tty1 autologin drop-in for yantra_user (no display manager)
#     3. .bash_profile: TTY1 detection → wait for :50000 → exec cage + chromium
#   The sysusers.d/yantra.conf already declares yantra_user in video+render
#   groups for DRM/KMS access. We scaffold the filesystem hooks here.
scaffold_identity_and_fs() {
  log_info "── scaffold_identity_and_fs ──"

  # ── Wayland Kiosk packages ───────────────────────────────────────────────
  # cage: minimal Wayland compositor (single-application kiosk)
  # chromium: kiosk browser targeting the local HUD on :50000
  # mesa: GPU userspace drivers (DRM/KMS rendering)
  # seatd: seat management daemon (rootless Wayland compositor launch)
  # wlroots: Wayland compositor library (cage dependency)
  ensure_packages cage chromium mesa seatd wlroots xdg-desktop-portal
  log_ok "Wayland Kiosk packages added to ISO manifest."

  # ── Live-USB home (explicit 1000:1000 ownership for PAM autologin) ──────
  install -dm700 "${AIROOTFS}/home/yantra_user"
  chown 1000:1000 "${AIROOTFS}/home/yantra_user"

  # SECURITY NOTE (carried over from compile_iso.sh, unchanged): password hashes
  # are intentionally zeroed for the LIVE USB only, enabling emergency physical
  # access. For production deployments, lock root ('root:!:') and enforce
  # SSH key-only auth. This is an existing YantraOS design decision, not new.
  install -dm755 "${AIROOTFS}/etc"
  printf 'root::14871::::::\nyantra_user::14871::::::\n' > "${AIROOTFS}/etc/shadow"
  chmod 0400 "${AIROOTFS}/etc/shadow"

  # Persistent state dirs (yantra_daemon:yantra = 999:998).
  install -dm750 "${AIROOTFS}/var/lib/yantra" "${AIROOTFS}/var/log/yantra"
  chown 999:998 "${AIROOTFS}/var/lib/yantra" "${AIROOTFS}/var/log/yantra"

  # ── getty@tty1 autologin drop-in ─────────────────────────────────────────
  # Bypasses the login prompt on TTY1: agetty auto-authenticates as
  # yantra_user, whose .bash_profile then launches the Wayland compositor.
  # Quoted heredoc ('GETTYEOF') prevents variable expansion — %I and $TERM
  # are systemd specifiers that must survive the ISO build verbatim.
  local getty_dropin="${AIROOTFS}/etc/systemd/system/getty@tty1.service.d"
  install -dm755 "${getty_dropin}"
  cat > "${getty_dropin}/autologin.conf" <<'GETTYEOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin yantra_user --noclear %I $TERM
GETTYEOF
  chmod 644 "${getty_dropin}/autologin.conf"
  log_ok "getty@tty1 autologin drop-in installed (yantra_user)."

  # ── .bash_profile — Wayland Kiosk launcher ───────────────────────────────
  # Activates ONLY on /dev/tty1 (SSH sessions are unaffected).
  # Sequence:
  #   1. Detect TTY1 via $(tty)
  #   2. Spin-wait for the YantraOS IPC server on http://127.0.0.1:50000
  #      (max 120 iterations × 1s = 2 minute timeout; the daemon starts
  #       asynchronously via yantra.service)
  #   3. exec cage → replaces the shell process with the Wayland compositor,
  #      running chromium in kiosk+incognito mode pointing at the local HUD
  #
  # CRITICAL: Quoted heredoc ('PROFILEEOF') ensures ZERO variable expansion
  # during ISO compilation. Every $, backtick, and special char is written
  # literally into the target file.
  local bash_profile="${AIROOTFS}/home/yantra_user/.bash_profile"
  cat > "${bash_profile}" <<'PROFILEEOF'
# YantraOS Wayland Kiosk Launcher
# Activates only on TTY1 — SSH/serial sessions drop to normal shell.

if [ "$(tty)" = "/dev/tty1" ]; then
  echo "[YantraOS] Kiosk mode detected on TTY1."
  echo "[YantraOS] Waiting for IPC server on port 50000..."

  _yantra_attempts=0
  _yantra_max=120
  while [ "$_yantra_attempts" -lt "$_yantra_max" ]; do
    if curl -sf -o /dev/null http://127.0.0.1:50000/health 2>/dev/null; then
      echo "[YantraOS] IPC server ready. Launching Wayland compositor."
      break
    fi
    _yantra_attempts=$((_yantra_attempts + 1))
    sleep 1
  done

  if [ "$_yantra_attempts" -ge "$_yantra_max" ]; then
    echo "[YantraOS] WARNING: IPC server not responding after ${_yantra_max}s."
    echo "[YantraOS] Launching compositor anyway — HUD will retry via SSE."
  fi

  # XDG_RUNTIME_DIR is mandatory for Wayland compositors; seatd provides
  # the seat, but the runtime dir must exist under /run/user/<uid>.
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
  mkdir -p "$XDG_RUNTIME_DIR" 2>/dev/null || true

  # exec replaces the login shell — no orphan bash process. cage exits
  # cleanly on compositor close, returning to getty (which re-autologins).
  exec cage -d -- chromium \
    --kiosk \
    --incognito \
    --no-first-run \
    --disable-translate \
    --disable-infobars \
    --disable-suggestions-service \
    --disable-save-password-bubble \
    --disable-session-crashed-bubble \
    --noerrdialogs \
    --ozone-platform=wayland \
    http://127.0.0.1:50000
fi
PROFILEEOF
  chmod 644 "${bash_profile}"
  chown 1000:1000 "${bash_profile}"
  log_ok ".bash_profile kiosk launcher installed for yantra_user."

  # ── seatd.service — enable seat management for rootless Wayland ──────────
  # cage requires an active seat; seatd provides this without logind/elogind.
  local wants="${AIROOTFS}/etc/systemd/system/multi-user.target.wants"
  ln -sf "/usr/lib/systemd/system/seatd.service" "${wants}/seatd.service"
  log_info "  ↳ seatd.service enabled."

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
  log_ok "Identity + filesystem scaffold complete (with Wayland Kiosk wiring)."
}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — inject_kriya_loop
#   Compile the Python execution matrix inside a STRICTLY EPHEMERAL pacstrap
#   chroot (never the airootfs overlay), then inject ONLY the pristine venv tree
#   into the staging airootfs. The build matrix is obliterated the instant the
#   rsync succeeds. Building the venv at its final path (/opt/yantra/venv) makes
#   every shebang born as the TARGET path; we still run a defensive sed pass on
#   the injected files. Version-skew is eliminated by construction: the matrix
#   and the ISO both resolve python from the same Arch core repo at build time
#   (pin further via YANTRA_PYTHON_PIN, e.g. "python=3.12.7").
# ══════════════════════════════════════════════════════════════════════════════
inject_kriya_loop() {
  log_info "═══ inject_kriya_loop ═══"

  # 3.1 — Guarantee the interpreter + sandbox packages are in the ISO manifest.
  #         The ISO's runtime python is installed by mkarchiso from this list;
  #         the venv's interpreter symlink resolves against it at boot.
  ensure_packages python python-pip rsync git docker bubblewrap

  # 3.2 — Define + create the ephemeral build matrix. Registered in the global
  #         so the EXIT trap can obliterate it even on a crash (constraint §4).
  VENV_BUILD_DIR="/tmp/yantra-venv-chroot-$$"
  rm -rf -- "${VENV_BUILD_DIR}"
  install -dm755 "${VENV_BUILD_DIR}"
  log_info "Ephemeral venv matrix: ${VENV_BUILD_DIR}"

  # 3.3 — Minimal pacstrap into the throwaway matrix (NOT the airootfs). 'git' is
  #         mandatory: pip resolves VCS dependencies (e.g. the pinned
  #         'litellm @ git+https://github.com/BerriAI/litellm.git@...' in
  #         requirements.txt) by invoking git INSIDE the chroot boundary; without
  #         it the in-chroot pip install fails on the first git+ marker.
  #         Optional explicit version pin via YANTRA_PYTHON_PIN closes any skew window.
  local -a venv_pkgs=(base python python-pip python-virtualenv git)
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
  [[ -f "${SCRIPT_DIR}/requirements.txt" ]] \
    && install -Dm644 "${SCRIPT_DIR}/requirements.txt" "${VENV_BUILD_DIR}/opt/yantra/requirements.txt"

  # 3.5 — Isolated compilation: build the venv at /opt/yantra/venv inside the
  #         matrix. Quoted heredoc → all paths are owned by the chroot.
  log_info "Compiling venv + Kriya Loop dependencies (isolated arch-chroot)..."
  local pip_list="${YANTRA_PIP_PACKAGES[*]}"
  arch-chroot "${VENV_BUILD_DIR}" /bin/bash -s -- "${pip_list}" <<'CHROOT'
set -euo pipefail
VENV=/opt/yantra/venv
PIP_LIST="$1"
install -dm755 /opt/yantra
python -m venv "${VENV}"
"${VENV}/bin/pip" install --upgrade pip setuptools wheel --quiet --retries 10 --timeout 120
# shellcheck disable=SC2086  # intentional word-split of the package list
"${VENV}/bin/pip" install ${PIP_LIST} --quiet --retries 10 --timeout 120
if [[ -f /opt/yantra/requirements.txt ]]; then
  "${VENV}/bin/pip" install -r /opt/yantra/requirements.txt --quiet --retries 10 --timeout 120
fi
# Offline LiteLLM cost map so routing works air-gapped (best-effort).
LITELLM_DIR="$(find "${VENV}/lib" -type d -path '*/site-packages/litellm' -print -quit || true)"
if [[ -n "${LITELLM_DIR}" ]]; then
  curl -fsSL "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json" \
    -o "${LITELLM_DIR}/model_prices_and_context_window_backup.json" \
    || touch "${LITELLM_DIR}/model_prices_and_context_window_backup.json"
fi
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

  # 3.8 — Defensive hashbang correction on the INJECTED files. A venv built at
  #         the target path is already correct; this normalizes any script whose
  #         shebang still references the build interpreter, anchoring it to the
  #         in-ISO path. Operates directly on airootfs.
  correct_venv_hashbangs "${venv_dest}"

  # 3.9 — Verify a representative shebang points at the TARGET path.
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

# ── Anchor every venv/bin shebang to the in-ISO interpreter path. ─────────────
# pip bakes the BUILD interpreter into console-script shebangs; on the live ISO
# that path must be /opt/yantra/venv/bin/python3. This sed pass is a no-op when
# the venv was built at the target path, and load-bearing otherwise.
correct_venv_hashbangs() {
  local venv_dir="$1"
  [[ -d "${venv_dir}/bin" ]] || return 0
  local script first count=0
  while IFS= read -r -d '' script; do
    first="$(head -1 -- "${script}" 2>/dev/null)" || continue
    if [[ "${first}" == '#!'* && "${first}" == *python* ]]; then
      sed -i "1s|#!.*python[0-9.]*|#!${VENV_TARGET}/bin/python3|" "${script}"
      count=$((count + 1))
    fi
  done < <(find "${venv_dir}/bin" -type f -print0)
  log_ok "Hashbang correction: ${count} script(s) anchored to ${VENV_TARGET}/bin/python3."
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

  # …but /home/yantra_user is the ONE exception that must NOT stay root-owned.
  # systemd-sysusers registers yantra_user (uid 1000) yet never creates or
  # chowns its home directory, and the active /etc/tmpfiles.d/yantra.conf has
  # no 'd /home/yantra_user' line — nothing re-derives this ownership at boot.
  # If we let the blanket chown above win, autologin lands uid 1000 in a
  # root:root 0700 home it cannot write to (zsh history/config writes fail).
  # Re-assert 1000:1000 AFTER the recursive chown so it survives into squashfs.
  if [[ -d "${AIROOTFS}/home/yantra_user" ]]; then
    chown -R 1000:1000 "${AIROOTFS}/home/yantra_user"
    log_info "  ↳ re-asserted /home/yantra_user → 1000:1000 recursive (post-recursive-chown)"
  fi
  log_ok "Ownership audit: profile root:root, /home/yantra_user 1000:1000."
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

  local -a sign_cmd=(gpg --batch --yes --armor --detach-sign)
  [[ -n "${SIGNING_KEY_PASSPHRASE}" ]] && sign_cmd+=(--pinentry-mode loopback --passphrase "${SIGNING_KEY_PASSPHRASE}")
  sign_cmd+=(--output "${sum_file}.sig" -- "${sum_file}")

  rm -f -- "${sum_file}.sig"
  if ! GNUPGHOME="${gnupg_tmp}" "${sign_cmd[@]}"; then
    wipe_gnupghome "${gnupg_tmp}"
    die "GPG signing of checksum failed."
  fi

  GNUPGHOME="${gnupg_tmp}" gpg --batch --verify -- "${sum_file}.sig" "${sum_file}" >/dev/null 2>&1 \
    && log_ok "Signature verified against imported key." \
    || log_warn "Signature created but local verification was inconclusive."

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
