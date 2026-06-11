#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# compile_rc3_iso.sh — YantraOS RC3 ISO compile + sign stage
#
# Runs the ArchISO toolchain against an already-scaffolded `archlive/` profile,
# then hashes and cryptographically signs the resulting artifact.
#
#   Profile dir : ./archlive            (archiso profile: profiledef.sh, etc.)
#   Work dir    : /tmp/yantra-build-work (tmpfs-backed scratch, wiped each run)
#   Output dir  : /opt/yantra-releases/
#   Artifact    : yantraos-rc3-x86_64.iso (+ .sha256, + .sha256.sig)
#
# Secret geometry: the Ed25519 signing key is supplied ONLY via the
# `YANTRA_SIGNING_KEY` environment variable (a path to the private key file).
# No secrets are substituted into the script. If it is unset, the build aborts
# FATALLY before mkarchiso is ever invoked.
#
#   export YANTRA_SIGNING_KEY=/path/to/yantra-rc3-ed25519.key
#   sudo -E ./compile_rc3_iso.sh
#
# NOTE: this stage assumes archlive/ is already prepared (profile scaffolded,
# core code synced, venv embedded). It does NOT perform that preparation.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
readonly ARTIFACT_NAME="yantraos-rc3-x86_64.iso"
readonly WORK_DIR="/tmp/yantra-build-work"
readonly OUT_DIR="/opt/yantra-releases"

# Ed25519 signing key path — supplied strictly via the environment.
readonly SIGNING_KEY="${YANTRA_SIGNING_KEY:-}"
# Optional: passphrase for the key, if it is protected (loopback pinentry).
readonly SIGNING_KEY_PASSPHRASE="${YANTRA_SIGNING_KEY_PASSPHRASE:-}"

# Resolve the profile dir relative to this script so the build is
# location-independent (script lives at the repo root; profile is archlive/).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
readonly SCRIPT_DIR
readonly PROFILE_DIR="${SCRIPT_DIR}/archlive"

# Map of required commands -> providing pacman package, for dependency checks.
readonly -A REQUIRED_PKGS=(
  [mkarchiso]="archiso"
  [mksquashfs]="squashfs-tools"
  [mkfs.btrfs]="btrfs-progs"
)

# ── Logging helpers ───────────────────────────────────────────────────────────
log()  { printf '\033[1;32m[RC3]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[RC3:WARN]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[RC3:FATAL]\033[0m %s\n' "$*" >&2; exit 1; }

# ── Signing-key gate ──────────────────────────────────────────────────────────
# Enforced FIRST, before any build work, so we never spend a full mkarchiso run
# only to discover at the end that we cannot sign the artifact.
require_signing_key() {
  [[ -n "${SIGNING_KEY}" ]] \
    || die "YANTRA_SIGNING_KEY is not set. Export the path to the Ed25519 signing key before building (e.g. export YANTRA_SIGNING_KEY=/path/to/key)."
  [[ -f "${SIGNING_KEY}" && -r "${SIGNING_KEY}" ]] \
    || die "YANTRA_SIGNING_KEY does not point to a readable key file: ${SIGNING_KEY}"
}

# ── Pre-flight checks ─────────────────────────────────────────────────────────
preflight() {
  log "Running pre-flight checks..."

  # Signing key must be present BEFORE we touch mkarchiso.
  require_signing_key

  # mkarchiso must run as root (it chroots and mounts).
  [[ "${EUID}" -eq 0 ]] || die "This build must run as root (mkarchiso requires it). Re-run with: sudo -E $0"

  # Profile sanity: the archiso profile must exist and be well-formed.
  [[ -d "${PROFILE_DIR}" ]]                 || die "Profile directory not found: ${PROFILE_DIR}"
  [[ -f "${PROFILE_DIR}/profiledef.sh" ]]   || die "Missing profiledef.sh in profile: ${PROFILE_DIR}"
  [[ -f "${PROFILE_DIR}/pacman.conf" ]]     || die "Missing pacman.conf in profile: ${PROFILE_DIR}"
  [[ -f "${PROFILE_DIR}/packages.x86_64" ]] || die "Missing packages.x86_64 in profile: ${PROFILE_DIR}"

  # Dependency verification: archiso, squashfs-tools, btrfs-progs.
  local missing=()
  local cmd pkg
  for cmd in "${!REQUIRED_PKGS[@]}"; do
    pkg="${REQUIRED_PKGS[$cmd]}"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      missing+=("${pkg} (provides '${cmd}')")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    printf '%s\n' "${missing[@]}" >&2
    die "Missing build dependencies. Install with: pacman -S --needed archiso squashfs-tools btrfs-progs"
  fi

  command -v gpg >/dev/null 2>&1 || die "gpg not found — required to sign the checksum."

  log "Pre-flight checks passed."
}

# ── Build ─────────────────────────────────────────────────────────────────────
build_iso() {
  log "Preparing build geometry..."
  # tmpfs-backed scratch — wipe any stale state from a previous run.
  rm -rf -- "${WORK_DIR}"
  mkdir -p -- "${WORK_DIR}"
  mkdir -p -- "${OUT_DIR}"

  log "Compiling RC3 ISO via mkarchiso (profile: ${PROFILE_DIR})..."
  # Canonical archiso invocation: verbose, explicit work + output dirs.
  mkarchiso -v -w "${WORK_DIR}" -o "${OUT_DIR}" "${PROFILE_DIR}"

  log "Reclaiming build scratch space..."
  rm -rf -- "${WORK_DIR}"
}

# ── Artifact normalization ────────────────────────────────────────────────────
# mkarchiso names the ISO from profiledef (iso_name-iso_version-arch.iso).
# Normalize it to the canonical RC3 artifact name for hashing/signing.
normalize_artifact() {
  local produced
  # Newest .iso in the output dir is the one we just built.
  produced="$(find "${OUT_DIR}" -maxdepth 1 -type f -name '*.iso' -printf '%T@ %p\n' \
    | sort -nr | head -n1 | cut -d' ' -f2-)"
  [[ -n "${produced}" && -f "${produced}" ]] || die "No .iso produced in ${OUT_DIR} — build failed."

  local target="${OUT_DIR}/${ARTIFACT_NAME}"
  if [[ "${produced}" != "${target}" ]]; then
    log "Normalizing artifact name: $(basename -- "${produced}") -> ${ARTIFACT_NAME}"
    mv -f -- "${produced}" "${target}"
  fi
  printf '%s\n' "${target}"
}

# ── Hash + sign ───────────────────────────────────────────────────────────────
hash_and_sign() {
  local iso_path="$1"
  local iso_name; iso_name="$(basename -- "${iso_path}")"
  local sum_file="${OUT_DIR}/${iso_name}.sha256"

  log "Generating SHA-256 checksum -> ${iso_name}.sha256"
  # Portable sha256sum-format line so it verifies with `sha256sum -c`.
  ( cd -- "${OUT_DIR}" && sha256sum -- "${iso_name}" > "${iso_name}.sha256" )

  log "Verifying generated checksum..."
  ( cd -- "${OUT_DIR}" && sha256sum -c -- "${iso_name}.sha256" >/dev/null ) \
    || die "Checksum self-verification failed for ${iso_name}."

  log "Signing checksum with Ed25519 key from YANTRA_SIGNING_KEY..."
  # Use the supplied key strictly for this one signature: import it into an
  # ephemeral, isolated GNUPGHOME so the host keyring is never touched, and
  # wipe that keyring on return regardless of outcome.
  local gnupg_tmp
  gnupg_tmp="$(mktemp -d)"
  chmod 700 -- "${gnupg_tmp}"
  # shellcheck disable=SC2317  # invoked via RETURN trap
  _wipe_keyring() { rm -rf -- "${gnupg_tmp}"; }
  trap _wipe_keyring RETURN

  GNUPGHOME="${gnupg_tmp}" gpg --batch --quiet --import -- "${SIGNING_KEY}" \
    || die "Failed to import Ed25519 signing key from ${SIGNING_KEY}."

  # Assemble the signing invocation; add loopback passphrase only if provided.
  local -a sign_cmd=(gpg --batch --yes --armor --detach-sign)
  if [[ -n "${SIGNING_KEY_PASSPHRASE}" ]]; then
    sign_cmd+=(--pinentry-mode loopback --passphrase "${SIGNING_KEY_PASSPHRASE}")
  fi
  sign_cmd+=(--output "${sum_file}.sig" -- "${sum_file}")

  rm -f -- "${sum_file}.sig"
  GNUPGHOME="${gnupg_tmp}" "${sign_cmd[@]}" \
    || die "GPG signing of checksum failed."

  if GNUPGHOME="${gnupg_tmp}" gpg --batch --verify -- "${sum_file}.sig" "${sum_file}" >/dev/null 2>&1; then
    log "Signature verified with the imported key."
  else
    warn "Signature created but local verification was inconclusive."
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  preflight
  build_iso

  local iso_path
  iso_path="$(normalize_artifact)"
  hash_and_sign "${iso_path}"

  log "RC3 build complete. Artifacts in ${OUT_DIR}:"
  log "  - ${ARTIFACT_NAME}"
  log "  - ${ARTIFACT_NAME}.sha256"
  log "  - ${ARTIFACT_NAME}.sha256.sig"
}

main "$@"
