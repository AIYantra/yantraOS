#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# YantraOS — Gold Master ISO Compilation Script (Phase 6)
# Target: archlive/compile_iso.sh
#
# Deterministic, idempotent build pipeline. Assumes the archlive/ directory
# is already scaffolded (profiledef.sh, packages.x86_64, airootfs/ tree).
# This script performs ONLY environment preparation, venv embedding, and
# mkarchiso invocation.
#
# Operations:
#   1. Root enforcement
#   2. State cleansing (work/ out/)
#   3. Symlink repair (multi-user.target.wants)
#   4. Python venv injection + hashbang correction
#   5. Host secrets verification + staging
#   6. CRLF sanitization + mkarchiso execution
#
# Usage:
#   sudo bash compile_iso.sh
#
# Authority: Euryale Ferox Private Limited
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
IFS=$'\n\t'

# ── Resolve SCRIPT_DIR to the directory containing this script ────────────────
# All paths are relative to this — no hardcoded /home/admin.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Derived paths ─────────────────────────────────────────────────────────────
AIROOTFS="${SCRIPT_DIR}/airootfs"
WORK_DIR="${SCRIPT_DIR}/work"
OUTPUT_DIR="${SCRIPT_DIR}/out"
VENV_BUILD="${AIROOTFS}/opt/yantra/venv"
VENV_TARGET="/opt/yantra/venv"
YANTRA_SRC="$(dirname "${SCRIPT_DIR}")"

# ── Color output ──────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[FAIL]${NC} $*" >&2; }

# ── Elapsed time tracking ────────────────────────────────────────────────────
BUILD_START=$(date +%s)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: ROOT ENFORCEMENT
# ══════════════════════════════════════════════════════════════════════════════

log_info "══════════════════════════════════════════════════════════════"
log_info "  YantraOS Gold Master — Phase 6 ISO Build Pipeline"
log_info "  Timestamp: $(date --iso-8601=seconds)"
log_info "══════════════════════════════════════════════════════════════"

if [[ $EUID -ne 0 ]]; then
    log_error "FATAL: This script requires root. Run: sudo bash $0"
    exit 1
fi
log_ok "Root privileges confirmed (EUID=0)."

# ── Dependency pre-flight ─────────────────────────────────────────────────────
REQUIRED_CMDS=("mkarchiso" "python3" "pip" "sed" "find" "install")
for cmd in "${REQUIRED_CMDS[@]}"; do
    if ! command -v "$cmd" &>/dev/null; then
        log_error "Required command not found: ${cmd}"
        log_error "Install: pacman -S archiso python python-pip"
        exit 1
    fi
done
log_ok "All build dependencies available."


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: STATE CLEANSING
# Nuke previous build artifacts to guarantee a pristine compilation matrix.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 2: State Cleansing ═══"

if [[ -d "${WORK_DIR}" ]]; then
    log_warn "Destroying stale work/ directory..."
    rm -rf "${WORK_DIR}"
fi

if [[ -d "${OUTPUT_DIR}" ]]; then
    log_warn "Destroying stale out/ directory..."
    rm -rf "${OUTPUT_DIR}"
fi

mkdir -p "${WORK_DIR}" "${OUTPUT_DIR}"
log_ok "Build matrix cleansed. work/ and out/ recreated."


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: SYMLINK REPAIR
# Windows-scaffolded symlinks in multi-user.target.wants/ are regular files,
# not UNIX symlinks. Delete them and recreate as proper ln -sf targets.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 3: Symlink Repair (multi-user.target.wants) ═══"

WANTS_DIR="${AIROOTFS}/etc/systemd/system/multi-user.target.wants"
install -dm755 "${WANTS_DIR}"

# ── Nuke all existing entries and rebuild from truth ─────────────────────────
# This is safer than surgical repair — guarantees no stale symlinks survive.
rm -f "${WANTS_DIR}"/*

# ── Service enablement matrix ────────────────────────────────────────────────
# Each entry maps to: ln -sf /usr/lib/systemd/system/<unit> <wants_dir>/<unit>
# These are the services that MUST start on boot for a functional YantraOS node.
ENABLE_SERVICES=(
    "docker.service"
    "ufw.service"
    "iwd.service"
    "sshd.service"
    "systemd-networkd.service"
    "systemd-resolved.service"
)

for unit in "${ENABLE_SERVICES[@]}"; do
    ln -sf "/usr/lib/systemd/system/${unit}" "${WANTS_DIR}/${unit}"
    log_info "  ↳ ${unit}"
done

# ── yantra.service lives in /etc/systemd/system/ (our custom unit) ───────────
# Its symlink target is the unit file we stage into airootfs, not /usr/lib/.
ln -sf "/etc/systemd/system/yantra.service" "${WANTS_DIR}/yantra.service"
log_info "  ↳ yantra.service (local unit)"

log_ok "Symlink matrix rebuilt: ${#ENABLE_SERVICES[@]}+1 services enabled."


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4: PYTHON VENV INJECTION (CRITICAL)
# Build a pip virtual environment inside airootfs/opt/yantra/venv/ so the
# ISO ships with all Python dependencies pre-resolved. Then surgically
# correct all hashbangs from the build-host path to the target ISO path.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 4: Python VENV Injection ═══"

# ── 4.1: Clean stale venv ────────────────────────────────────────────────────
if [[ -d "${VENV_BUILD}" ]]; then
    log_warn "Existing venv detected — destroying for clean rebuild."
    rm -rf "${VENV_BUILD}"
fi

# ── 4.2: Create venv ─────────────────────────────────────────────────────────
log_info "Creating venv at: ${VENV_BUILD}"
python3 -m venv "${VENV_BUILD}"
log_ok "Venv skeleton created."

# ── 4.3: Activate and install dependencies ───────────────────────────────────
# shellcheck disable=SC1091
source "${VENV_BUILD}/bin/activate"

log_info "Upgrading pip/setuptools/wheel..."
pip install --upgrade pip setuptools wheel \
    --quiet --retries 10 --timeout 120

# Core packages explicitly required by spec:
YANTRA_PIP_PACKAGES=(
    "fastapi"
    "uvicorn[standard]"
    "litellm"
    "chromadb"
    "docker"
    "sdnotify"
    "pynvml"
    "textual"
    "rich"
)

log_info "Installing YantraOS Python dependencies..."
pip install "${YANTRA_PIP_PACKAGES[@]}" \
    --quiet --retries 10 --timeout 120

# Install remaining deps from requirements.txt (idempotent — pip skips
# already-satisfied packages)
if [[ -f "${YANTRA_SRC}/requirements.txt" ]]; then
    log_info "Installing from requirements.txt (supplementary)..."
    pip install -r "${YANTRA_SRC}/requirements.txt" \
        --quiet --retries 10 --timeout 120
fi

log_info "Downloading LiteLLM offline cost map backup..."
wget -q "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json" \
    -O "${VENV_BUILD}/lib/python3.14/site-packages/litellm/model_prices_and_context_window_backup.json" || true

deactivate
log_ok "All Python dependencies installed into venv."

# ── 4.4: HASHBANG CORRECTION (THE CRITICAL FIX) ─────────────────────────────
# pip writes the BUILD HOST's absolute Python path as the shebang in every
# script under venv/bin/. On the live ISO, this path doesn't exist.
# Without this sed pass, every venv script — pip, litellm, textual — will
# fail with "bad interpreter: No such file or directory", and the daemon
# will not start. The OS is bricked.
#
# We rewrite: #!/home/admin/archlive/airootfs/opt/yantra/venv/bin/python3
#         to: #!/opt/yantra/venv/bin/python3

log_info "Correcting hashbangs in venv/bin/ scripts..."
HASHBANG_COUNT=0

while IFS= read -r -d '' script; do
    first_line=$(head -1 "$script" 2>/dev/null) || continue
    if [[ "$first_line" == "#!"* ]] && echo "$first_line" | grep -q "python"; then
        sed -i "1s|#!.*python[0-9.]*|#!${VENV_TARGET}/bin/python3|" "$script"
        HASHBANG_COUNT=$((HASHBANG_COUNT + 1))
    fi
done < <(find "${VENV_BUILD}/bin" -type f -executable -print0)

log_ok "Hashbangs corrected in ${HASHBANG_COUNT} script(s)."

# ── 4.5: Verify the fix ─────────────────────────────────────────────────────
VERIFY_SCRIPT="${VENV_BUILD}/bin/pip"
if [[ -f "${VERIFY_SCRIPT}" ]]; then
    VERIFY_LINE=$(head -1 "${VERIFY_SCRIPT}")
    if echo "${VERIFY_LINE}" | grep -q "${VENV_TARGET}"; then
        log_ok "Hashbang verification passed: ${VERIFY_LINE}"
    else
        log_error "FATAL: Hashbang verification FAILED: ${VERIFY_LINE}"
        log_error "Expected: #!${VENV_TARGET}/bin/python3"
        exit 1
    fi
fi


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5: SECRETS VERIFICATION
# The ISO MUST ship with valid API credentials. A YantraOS node without
# inference credentials is operationally dead — cloud fallback in the
# hybrid_router silently fails, leaving the daemon unable to reason.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 5: Secrets Verification ═══"

HOST_SECRETS="/etc/yantra/host_secrets.env"
STAGED_SECRETS="${AIROOTFS}/etc/yantra/host_secrets.env"

if [[ ! -f "${HOST_SECRETS}" ]]; then
    log_error "══════════════════════════════════════════════════════════════"
    log_error "  FATAL: ${HOST_SECRETS} not found on build host."
    log_error "  Cannot ship a brain-dead AI. Populate this file with:"
    log_error "    GEMINI_API_KEY=<your-key>"
    log_error "    YANTRA_DAEMON_KEY=<your-key>"
    log_error "══════════════════════════════════════════════════════════════"
    exit 1
fi

# ── Validate key presence (not just file existence) ──────────────────────────
GEMINI_KEY=$(grep -oP '^GEMINI_API_KEY=\K.*' "${HOST_SECRETS}" | tr -d "\"'" | xargs)
if [[ -z "${GEMINI_KEY}" || "${GEMINI_KEY}" == "PLACEHOLDER" || "${GEMINI_KEY}" == "your-key-here" ]]; then
    log_error "GEMINI_API_KEY is missing, empty, or placeholder in ${HOST_SECRETS}"
    exit 1
fi
log_ok "GEMINI_API_KEY validated (${#GEMINI_KEY} chars)."

# ── Stage secrets into airootfs ──────────────────────────────────────────────
install -dm700 "$(dirname "${STAGED_SECRETS}")"
install -Dm600 "${HOST_SECRETS}" "${STAGED_SECRETS}"

# ── Cryptographic sanitization ───────────────────────────────────────────────
# systemd's EnvironmentFile passes quote characters literally.
# GEMINI_API_KEY="AIza..." becomes the string '"AIza..."' including quotes,
# poisoning every LiteLLM request.
sed -i "s/['\"]//g" "${STAGED_SECRETS}"
sed -i 's/[[:space:]]*$//' "${STAGED_SECRETS}"

log_ok "Secrets staged to airootfs (0600, quote-stripped)."


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5.5: AMNESIA PROTOCOL + CRLF SANITIZATION
# Purge host-machine state artifacts and Windows line endings.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 5.5: Amnesia Protocol + CRLF Sanitization ═══"

# ── Amnesia Protocol ─────────────────────────────────────────────────────────
# Purge residual host state so the ISO boots at Iteration #1 with clean memory.
find "${AIROOTFS}/opt/yantra/" -name "*.json" -type f -delete 2>/dev/null || true
find "${AIROOTFS}/opt/yantra/" -name "*.pyc" -type f -delete 2>/dev/null || true
rm -rf "${AIROOTFS}/opt/yantra/core/__pycache__" 2>/dev/null || true
rm -rf "${AIROOTFS}/opt/yantra/__pycache__" 2>/dev/null || true
rm -rf "${AIROOTFS}/var/lib/yantra/chromadb" 2>/dev/null || true
rm -rf "${AIROOTFS}/var/lib/yantra/chroma" 2>/dev/null || true
log_ok "Amnesia Protocol complete — no host state will bleed into ISO."

# ── CRLF → LF ────────────────────────────────────────────────────────────────
# Windows development contaminates text files with \r\n. Shell scripts and
# systemd units will silently malfunction with CRLF.
CRLF_COUNT=0

while IFS= read -r -d '' file; do
    if file "$file" 2>/dev/null | grep -q "text"; then
        if grep -qP '\r$' "$file" 2>/dev/null; then
            sed -i 's/\r$//' "$file"
            CRLF_COUNT=$((CRLF_COUNT + 1))
        fi
    fi
done < <(find "${SCRIPT_DIR}" -type f \( \
    -name "*.sh" -o -name "*.py" -o -name "*.conf" -o -name "*.service" \
    -o -name "*.hook" -o -name "*.rules" -o -name "*.env" -o -name "*.cfg" \
    -o -name "*.txt" -o -name "*.preset" -o -name "*.network" \
    -o -name "profiledef.sh" -o -name "packages.x86_64" \
    -o -name "pacman.conf" -o -name ".zprofile" -o -name ".zlogin" \
    \) -print0)

if [[ $CRLF_COUNT -gt 0 ]]; then
    log_ok "Sanitized ${CRLF_COUNT} file(s) from CRLF → LF."
else
    log_ok "No CRLF contamination detected."
fi


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 6: OWNERSHIP AUDIT + MKARCHISO EXECUTION
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 6: Compilation (mkarchiso) ═══"

# ── Root ownership enforcement ───────────────────────────────────────────────
# mkarchiso maps UIDs from the build tree into the squashfs. Non-root
# ownership on any file cascades into the immutable ISO as a security defect.
log_info "Enforcing root:root ownership on entire build tree..."
chown -R root:root "${SCRIPT_DIR}"
log_ok "Ownership audit passed."


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5.7: IDENTITY MATRIX SCAFFOLD
# We use systemd-sysusers (via airootfs/usr/lib/sysusers.d/yantra.conf) to
# construct the users declaratively on boot.
# We physically construct the home directory here to ensure agetty does not
# fail if pam_mkhomedir ignores it.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 5.7: Identity Matrix Scaffold ═══"

# ── 5.7.1: Home directory creation with POSIX ownership ─────────────────
# CRITICAL: Without exact UID/GID ownership, agetty autologin → PAM → fails.
# This runs AFTER chown -R root:root, so we must explicitly set 1000:1000.
install -dm700 "${AIROOTFS}/home/yantra_user"
chown 1000:1000 "${AIROOTFS}/home/yantra_user"
log_ok "Home directory created: /home/yantra_user (700, 1000:1000)."

log_ok "Identity Matrix Scaffold complete."


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5.8: FILESYSTEM SCAFFOLD
# yantra.service declares ReadWritePaths=/var/lib/yantra and
# RequiresMountsFor=/var/lib/yantra. If these don't exist in the squashfs,
# systemd's namespace setup panics with status=226/NAMESPACE before the
# service binary even executes. We scaffold the persistent directories here.
#
# NOTE: /run/yantra is NOT created — /run is an ephemeral tmpfs mounted by
# the kernel before pid1. The tmpfiles.d/yantra.conf rule handles it.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 5.8: Filesystem Scaffold ═══"

# ── Persistent state directories ─────────────────────────────────────────
mkdir -p "${AIROOTFS}/var/lib/yantra"
mkdir -p "${AIROOTFS}/var/log/yantra"
chown 999:998 "${AIROOTFS}/var/lib/yantra" "${AIROOTFS}/var/log/yantra"
chmod 0750 "${AIROOTFS}/var/lib/yantra" "${AIROOTFS}/var/log/yantra"
log_ok "Scaffolded: /var/lib/yantra, /var/log/yantra (999:998, 0750)."

# ── Verify tmpfiles.d rule is staged ─────────────────────────────────────
if [[ -f "${AIROOTFS}/etc/tmpfiles.d/yantra.conf" ]]; then
    log_ok "tmpfiles.d/yantra.conf present — /run/yantra will be created at boot."
else
    log_warn "tmpfiles.d/yantra.conf MISSING — /run/yantra may not exist at boot!"
fi


# ── Final root privilege check (belt-and-suspenders) ─────────────────────────
if [[ $EUID -ne 0 ]]; then
    log_error "FATAL: Lost root privileges before mkarchiso. Aborting."
    exit 1
fi

# ── Execute mkarchiso ─────────────────────────────────────────────────────────
log_info "Starting mkarchiso..."
log_info "  Profile:  ${SCRIPT_DIR}"
log_info "  Work dir: ${WORK_DIR}"
log_info "  Output:   ${OUTPUT_DIR}"
echo ""

mkarchiso -v -w "${WORK_DIR}" -o "${OUTPUT_DIR}" "${SCRIPT_DIR}"

BUILD_EXIT=$?
BUILD_END=$(date +%s)
BUILD_ELAPSED=$(( BUILD_END - BUILD_START ))

if [[ $BUILD_EXIT -eq 0 ]]; then
    echo ""
    log_ok "══════════════════════════════════════════════════════════════"
    log_ok "  YantraOS Gold Master — ISO BUILD SUCCESSFUL"
    log_ok "  Elapsed: ${BUILD_ELAPSED}s"
    log_ok "  Output:"
    ls -lh "${OUTPUT_DIR}/"*.iso 2>/dev/null || true
    log_ok "══════════════════════════════════════════════════════════════"
else
    echo ""
    log_error "══════════════════════════════════════════════════════════════"
    log_error "  mkarchiso FAILED (exit code ${BUILD_EXIT})"
    log_error "  Elapsed: ${BUILD_ELAPSED}s"
    log_error "  Inspect: ${WORK_DIR} for partial artifacts."
    log_error "══════════════════════════════════════════════════════════════"
    exit $BUILD_EXIT
fi

# ── Post-build cleanup ───────────────────────────────────────────────────────
log_info "Cleaning work directory..."
rm -rf "${WORK_DIR}"
log_ok "Build complete. ISO ready for deployment."
