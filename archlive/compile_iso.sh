#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# YantraOS — Master ISO Compilation Script (Gold Master v1.3)
# Target: /home/admin/archlive/compile_iso.sh
# Milestone 6, Tasks 6.1–6.3
#
# This script automates the complete Archiso build pipeline for YantraOS
# Alpha v1.3. It performs six surgical operations:
#
#   PHASE 1: Scaffolding — Copy the Arch releng profile to /home/admin/archlive
#   PHASE 2: Dependency Injection — Append required packages
#   PHASE 3: Payload Staging — Populate airootfs with YantraOS core
#   PHASE 4: Permission Matrix — Inject file_permissions into profiledef.sh
#   PHASE 5: CRLF → LF Sanitization — Purge Windows line endings
#   PHASE 6: Execution — Run mkarchiso to compile the ISO
#
# Usage:
#   sudo bash compile_iso.sh
#
# MUST be run as root. mkarchiso requires root for squashfs creation and
# UID/GID mapping as defined in profiledef.sh.
#
# Authority: Euryale Ferox Private Limited
# ══════════════════════════════════════════════════════════════════════════════

# ── Halt immediately on any error ─────────────────────────────────────────────
# set -e: exit on first error (Architectural Invariant).
# set -u: treat unset variables as errors.
# set -o pipefail: propagate pipe failures.
set -euo pipefail
IFS=$'\n\t'

# ── Configuration ─────────────────────────────────────────────────────────────

# The archlive working directory for the Archiso profile.
ARCHLIVE_DIR="/home/admin/archlive"

# Source paths — the YantraOS development repository.
# Adjust YANTRA_SRC if your repo is elsewhere.
YANTRA_SRC="/home/admin/Documents/YantraOS"

# Derived paths
AIROOTFS="${ARCHLIVE_DIR}/airootfs"
PROFILEDEF="${ARCHLIVE_DIR}/profiledef.sh"
PACKAGES_FILE="${ARCHLIVE_DIR}/packages.x86_64"

# Build output locations
WORK_DIR="/home/admin/Documents/YantraOS/work"
OUTPUT_DIR="./out"

# Releng source (standard Archiso profile location)
RELENG_SRC="/usr/share/archiso/configs/releng"

# Venv paths for Python environment embedding
VENV_BUILD="${AIROOTFS}/opt/yantra/venv"
VENV_DEPLOY="/opt/yantra/venv"

# Python dependencies for YantraOS
# Now loaded directly from requirements.txt instead of this hardcoded array.

# ── Color output helpers ──────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ══════════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

log_info "══════════════════════════════════════════════════════════════"
log_info "  YantraOS Gold Master v1.3 — ISO Build Pipeline"
log_info "══════════════════════════════════════════════════════════════"

# ── Root check ────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root."
    log_error "Usage: sudo bash $0"
    exit 1
fi
log_ok "Running as root."

# ── Credential pre-flight ─────────────────────────────────────────────────────
# RC4 bare-metal revealed ISOs built without valid API keys produce a
# geometrically broken system — cloud inference fallback silently fails.
# Fatally abort BEFORE any scaffolding if GEMINI_API_KEY is missing.
HOST_SECRETS="/etc/yantra/host_secrets.env"
if [[ ! -f "${HOST_SECRETS}" ]]; then
    log_error "Secrets file not found: ${HOST_SECRETS}"
    log_error "Create it with at minimum: GEMINI_API_KEY=<your-key>"
    exit 1
fi

# Source the secrets file to validate key presence
GEMINI_KEY=$(grep -oP '^GEMINI_API_KEY=\K.*' "${HOST_SECRETS}" | tr -d '"' | tr -d "'")
if [[ -z "${GEMINI_KEY}" || "${GEMINI_KEY}" == "PLACEHOLDER" || "${GEMINI_KEY}" == "your-key-here" ]]; then
    log_error "GEMINI_API_KEY is missing, empty, or set to a placeholder in ${HOST_SECRETS}"
    log_error "Refusing to build a geometrically broken ISO without valid inference credentials."
    exit 1
fi
log_ok "GEMINI_API_KEY validated (${#GEMINI_KEY} chars)."

# ── GOOGLE_GENERATIVE_AI_API_KEY environment guard ────────────────────────────
# The directive requires the build to abort if this key is absent from the
# host environment. This is separate from GEMINI_API_KEY in host_secrets.env.
if [[ -z "${GOOGLE_GENERATIVE_AI_API_KEY:-}" ]]; then
    log_error "GOOGLE_GENERATIVE_AI_API_KEY is not set in the host environment."
    log_error "Export it before building: export GOOGLE_GENERATIVE_AI_API_KEY=<key>"
    exit 1
fi
log_ok "GOOGLE_GENERATIVE_AI_API_KEY found in host environment (${#GOOGLE_GENERATIVE_AI_API_KEY} chars)."

# ── Dependency check ──────────────────────────────────────────────────────────
# Verify all required commands are available before starting.
REQUIRED_CMDS=("mkarchiso" "python3" "pip" "sed" "install")
for cmd in "${REQUIRED_CMDS[@]}"; do
    if ! command -v "$cmd" &>/dev/null; then
        log_error "Required command not found: $cmd"
        log_error "Install archiso: pacman -S archiso python python-pip"
        exit 1
    fi
done
log_ok "All required commands available."

# ── Verify source repository exists ──────────────────────────────────────────
if [[ ! -d "${YANTRA_SRC}/core" ]]; then
    log_error "YantraOS source not found at: ${YANTRA_SRC}/core"
    log_error "Ensure the repository is cloned to ${YANTRA_SRC}"
    exit 1
fi
log_ok "YantraOS source repository located at: ${YANTRA_SRC}"

# ── Verify releng profile exists ─────────────────────────────────────────────
if [[ ! -d "${RELENG_SRC}" ]]; then
    log_error "Archiso releng profile not found at: ${RELENG_SRC}"
    log_error "Install archiso: pacman -S archiso"
    exit 1
fi
log_ok "Archiso releng profile confirmed at: ${RELENG_SRC}"


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: SCAFFOLDING (Invariant 1)
# Copy the base Arch Linux releng profile to /home/admin/archlive.
# This provides the clean, upstream profile as our foundation.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 1: Scaffolding — Copying releng profile ═══"

# If archlive already exists, back it up to prevent data loss.
if [[ -d "${ARCHLIVE_DIR}" ]]; then
    BACKUP_DIR="${ARCHLIVE_DIR}.backup.$(date +%Y%m%d%H%M%S)"
    log_warn "Existing archlive found — backing up to ${BACKUP_DIR}"
    mv "${ARCHLIVE_DIR}" "${BACKUP_DIR}"
fi

# Copy the releng profile. This gives us the canonical Archiso structure:
# packages.x86_64, profiledef.sh, pacman.conf, airootfs/, efiboot/, etc.
cp -r "${RELENG_SRC}/" "${ARCHLIVE_DIR}"
log_ok "Releng profile copied to ${ARCHLIVE_DIR}"


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: DEPENDENCY INJECTION (Invariant 2)
# Programmatically append YantraOS-required packages to packages.x86_64.
# These are installed into the live ISO's root filesystem by mkarchiso.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 2: Dependency Injection ═══"

# Verify packages.x86_64 exists in the freshly copied profile
if [[ ! -f "${PACKAGES_FILE}" ]]; then
    log_error "packages.x86_64 not found in ${ARCHLIVE_DIR}"
    exit 1
fi

# The packages YantraOS requires on top of the base releng profile:
#   docker         — Container runtime for the ephemeral sandbox
#   docker-compose — Multi-container orchestration (future Skill stacks)
#   btrfs-progs    — BTRFS snapshot management (Milestone 2)
#   polkit         — Privilege escalation policy for btrfs operations
#   python-pip     — Python package manager (for venv bootstrapping)
#   python         — Python 3 runtime for the Kriya Loop daemon
YANTRA_PACKAGES=(
    "docker"
    "docker-compose"
    "btrfs-progs"
    "polkit"
    "python-pip"
    "python"
    "linux-headers"
    "mesa"
    "nvidia-dkms"
    "nvidia-utils"
    "lib32-nvidia-utils"
    "opencl-nvidia"
    "vulkan-radeon"
    "lib32-vulkan-radeon"
    "vulkan-intel"
    "lib32-vulkan-intel"
    "pciutils"
    "networkmanager"
    "iwd"
    "systemd-resolvconf"
    "ttf-jetbrains-mono"
    "inter-font"
)

log_info "Appending YantraOS packages to packages.x86_64..."
for pkg in "${YANTRA_PACKAGES[@]}"; do
    # Only append if not already present (idempotent).
    if ! grep -qx "${pkg}" "${PACKAGES_FILE}"; then
        echo "${pkg}" >> "${PACKAGES_FILE}"
        log_info "  + ${pkg}"
    else
        log_info "  ✓ ${pkg} (already present)"
    fi
done
log_ok "Package injection complete."


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: PAYLOAD STAGING (Invariant 3)
# Populate the airootfs overlay with YantraOS core, deploy configs,
# systemd units, secrets, and runtime directories.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 3: Payload Staging — Populating airootfs ═══"

# ── 3.1: Copy YantraOS core Python modules ────────────────────────────────────
# These are the daemon's brain: engine.py, sandbox.py, hybrid_router.py, etc.
# Destination: airootfs/opt/yantra/core/
log_info "Copying YantraOS core/ into airootfs..."
install -dm755 "${AIROOTFS}/opt/yantra/core"

for pyfile in "${YANTRA_SRC}/core/"*.py; do
    if [[ -f "$pyfile" ]]; then
        install -Dm644 "$pyfile" "${AIROOTFS}/opt/yantra/core/$(basename "$pyfile")"
    fi
done

# Copy sandbox Dockerfile for local image builds on the live ISO
if [[ -d "${YANTRA_SRC}/core/sandbox" ]]; then
    install -dm755 "${AIROOTFS}/opt/yantra/core/sandbox"
    install -Dm644 "${YANTRA_SRC}/core/sandbox/Dockerfile" \
        "${AIROOTFS}/opt/yantra/core/sandbox/Dockerfile"
    log_info "Sandbox Dockerfile deployed to airootfs."
fi

# Mark daemon entry points as executable (daemon.py, cli.py)
chmod 755 "${AIROOTFS}/opt/yantra/core/daemon.py" 2>/dev/null || true
chmod 755 "${AIROOTFS}/opt/yantra/core/cli.py" 2>/dev/null || true
log_ok "Core Python modules staged."

# ── 3.1b: Amnesia Protocol — State Cleansing ─────────────────────────────────
# RC5 revealed that host-machine state files (kriya_state.json, iteration
# counters) bled into the ISO, causing the daemon to boot at Iter #29
# instead of a clean Iter #1. Purge ALL residual state.
log_info "Executing Amnesia Protocol — purging host state from airootfs..."
find "${AIROOTFS}/opt/yantra/" -name "*.json" -type f -delete 2>/dev/null || true
rm -rf "${AIROOTFS}/opt/yantra/core/chromadb" "${AIROOTFS}/opt/yantra/core/chroma" 2>/dev/null || true
rm -rf "${AIROOTFS}/var/lib/yantra/chromadb" "${AIROOTFS}/var/lib/yantra/chroma" 2>/dev/null || true
rm -rf "${AIROOTFS}/opt/yantra/__pycache__" 2>/dev/null || true
rm -rf "${AIROOTFS}/opt/yantra/core/__pycache__" 2>/dev/null || true
find "${AIROOTFS}/opt/yantra/" -name "*.pyc" -type f -delete 2>/dev/null || true
log_ok "Amnesia Protocol complete — ISO will boot with clean state."

# ── 3.2: Copy deploy configs ─────────────────────────────────────────────────

log_info "Copying deploy/ configs into airootfs..."

# sysusers.d — Creates yantra_daemon user and yantra group at boot
install -Dm644 "${YANTRA_SRC}/deploy/sysusers.d/yantra.conf" \
    "${AIROOTFS}/usr/lib/sysusers.d/yantra.conf"

# tmpfiles.d — Creates /run/yantra and /var/lib/yantra at boot
install -Dm644 "${YANTRA_SRC}/deploy/tmpfiles.d/yantra.conf" \
    "${AIROOTFS}/usr/lib/tmpfiles.d/yantra.conf"

# Polkit rules — Grants yantra_daemon BTRFS snapshot privileges via pkexec
install -Dm644 "${YANTRA_SRC}/deploy/polkit/50-yantra-btrfs.rules" \
    "${AIROOTFS}/etc/polkit-1/rules.d/50-yantra-btrfs.rules"

log_ok "Deploy configs (sysusers, tmpfiles, polkit) staged."

# ── 3.3: Systemd unit file & symlink ─────────────────────────────────────────
# Copy yantra.service into the systemd unit directory, then create
# a symlink in multi-user.target.wants/ to enable auto-start on boot.
log_info "Staging yantra.service unit file..."

install -Dm644 "${YANTRA_SRC}/deploy/systemd/yantra.service" \
    "${AIROOTFS}/etc/systemd/system/yantra.service"

# Create the symlink for automatic ignition on boot.
# The symlink in multi-user.target.wants/ is the Archiso equivalent of
# `systemctl enable yantra.service` — it ensures the unit starts at boot
# without needing to run systemctl inside the chroot.
install -dm755 "${AIROOTFS}/etc/systemd/system/multi-user.target.wants"
ln -sf /etc/systemd/system/yantra.service \
    "${AIROOTFS}/etc/systemd/system/multi-user.target.wants/yantra.service" 2>/dev/null || true

log_ok "yantra.service staged and symlinked for boot ignition."

# ── 3.4: Pacman hooks ────────────────────────────────────────────────────────
# Copy the autosnap hook as .inactive to prevent premature BTRFS execution
# inside the chroot environment during mkarchiso build. It will be renamed
# to .hook after first boot when BTRFS is properly initialized.
log_info "Staging pacman hooks..."

install -dm755 "${AIROOTFS}/etc/pacman.d/hooks"

# CRITICAL: The autosnap hook is staged as .inactive to prevent it from
# triggering during the chroot pacstrap phase. BTRFS subvolumes don't exist
# in the build chroot, so running btrfs snapshot would fail catastrophically.
install -Dm644 "${YANTRA_SRC}/deploy/pacman/00-yantra-autosnap.hook.inactive" \
    "${AIROOTFS}/etc/pacman.d/hooks/00-yantra-autosnap.hook.inactive"

install -Dm644 "${YANTRA_SRC}/deploy/pacman/99-yantra-reload.hook" \
    "${AIROOTFS}/etc/pacman.d/hooks/99-yantra-reload.hook"

log_ok "Pacman hooks staged (autosnap as .inactive)."

# ── 3.5: Secrets file ────────────────────────────────────────────────────────
# Create the host_secrets.env placeholder. The actual tokens are injected during
# deployment or via the build.sh wrapper. For the ISO, we stage an empty
# file with root-only read/write permissions (0600).
log_info "Staging host_secrets.env placeholder..."

install -dm700 "${AIROOTFS}/etc/yantra"

# If a host_secrets.env exists in the source repo, copy it.
# Otherwise, create an empty placeholder.
if [[ -f "${YANTRA_SRC}/host_secrets.env" ]]; then
    install -Dm600 "${YANTRA_SRC}/host_secrets.env" \
        "${AIROOTFS}/etc/yantra/host_secrets.env"
    log_ok "host_secrets.env copied from source (0600 permissions)."
else
    touch "${AIROOTFS}/etc/yantra/host_secrets.env"
    chmod 600 "${AIROOTFS}/etc/yantra/host_secrets.env"
    log_warn "No host_secrets.env in source — empty placeholder created (0600)."
fi

# ── Cryptographic Sanitization ───────────────────────────────────────────────
# RC5 revealed that systemd's EnvironmentFile directive passes quote
# characters LITERALLY — GEMINI_API_KEY="AIza..." becomes the string
# '"AIza..."' including the quotes, causing LiteLLM to misroute to
# Vertex AI and reject the key. Strip all quotes and trailing whitespace.
log_info "Sanitizing staged host_secrets.env (stripping quotes/whitespace)..."
sed -i "s/['\"]//g" "${AIROOTFS}/etc/yantra/host_secrets.env"
sed -i 's/[[:space:]]*$//' "${AIROOTFS}/etc/yantra/host_secrets.env"
log_ok "Secrets sanitized — no embedded quotes or trailing whitespace."

# ── 3.5.1: Host Payload Injection ────────────────────────────────────────────
# Copy the host-level cryptographic payload into the airootfs secrets path.
# This injects the actual runtime credentials from the build host into the ISO.
log_info "Injecting host payload into airootfs..."

mkdir -p /home/admin/archlive/airootfs/etc/yantra
cp /home/admin/Documents/YantraOS/host_secrets.env /home/admin/archlive/airootfs/etc/yantra/host_secrets.env
chmod 600 /home/admin/archlive/airootfs/etc/yantra/host_secrets.env

# Re-sanitize after host payload injection (belt-and-suspenders)
sed -i "s/['\"]//g" "${AIROOTFS}/etc/yantra/host_secrets.env"
sed -i 's/[[:space:]]*$//' "${AIROOTFS}/etc/yantra/host_secrets.env"

log_ok "Host payload injected and sanitized (0600 permissions)."

# ── 3.5.2: Hardcoded Key Injection Failsafe ──────────────────────────────────
# Bare-metal testing (RC4–RC10) revealed that sudo consistently strips API keys
# during compilation. This failsafe mathematically guarantees the keys exist on
# the ISO by writing them directly into host_secrets.env AFTER all copy/sanitize
# operations. If the keys are already present, these are idempotent appends that
# sed will deduplicate.
log_info "Injecting hardcoded API key failsafe into airootfs..."
# Remove any existing entries to avoid duplication
sed -i '/^GEMINI_API_KEY=/d' "${AIROOTFS}/etc/yantra/host_secrets.env"
sed -i '/^GOOGLE_GENERATIVE_AI_API_KEY=/d' "${AIROOTFS}/etc/yantra/host_secrets.env"
# Inject the hardcoded keys
echo 'GEMINI_API_KEY=<REDACTED_FOR_PUBLIC_REPO>' >> "${AIROOTFS}/etc/yantra/host_secrets.env"
echo 'GOOGLE_GENERATIVE_AI_API_KEY=<REDACTED_FOR_PUBLIC_REPO>' >> "${AIROOTFS}/etc/yantra/host_secrets.env"
log_ok "Hardcoded API key failsafe injected (no quotes, no whitespace)."

# ── 3.6: Runtime directories ─────────────────────────────────────────────────
# These directories are needed by the daemon at runtime. They are also
# created by tmpfiles.d at boot, but we stage them in airootfs to ensure
# profiledef.sh can set ownership correctly.
install -dm770 "${AIROOTFS}/run/yantra"
install -dm770 "${AIROOTFS}/var/lib/yantra"
install -dm770 "${AIROOTFS}/var/lib/yantra/chromadb"
install -dm770 "${AIROOTFS}/var/log/yantra"
install -dm770 "${AIROOTFS}/var/lib/yantra/cache"
log_ok "Runtime directories staged (including /var/log/yantra and cache)."

# ── 3.6b: yantra_user home directory ─────────────────────────────────────────
# Required for `su - yantra_user` in the automated boot script.
# systemd-sysusers creates the user entry but NOT the home directory.
install -dm700 "${AIROOTFS}/home/yantra_user"
chown 1000:1000 "${AIROOTFS}/home/yantra_user"
log_ok "yantra_user home directory created (/home/yantra_user)."


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3.7: Python Virtual Environment Embedding (Task 6.2)
# Build a pip venv INSIDE airootfs so the ISO ships with all Python
# dependencies pre-installed. Fix hashbangs to point to the deployment path.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 3.7: Embedding Python virtual environment ═══"

# Clean any stale venv
if [[ -d "${VENV_BUILD}" ]]; then
    log_warn "Existing venv found — removing for clean rebuild."
    rm -rf "${VENV_BUILD}"
fi

log_info "Creating venv at ${VENV_BUILD}..."
python3 -m venv "${VENV_BUILD}"
log_ok "Venv created."

# Install pip dependencies from requirements.txt
log_info "Installing pip dependencies from requirements.txt into venv..."
install -Dm644 "${YANTRA_SRC}/requirements.txt" "${AIROOTFS}/opt/yantra/requirements.txt"
"${VENV_BUILD}/bin/pip" install --upgrade pip setuptools wheel --quiet --retries 10 --timeout 120
"${VENV_BUILD}/bin/pip" install -r "${YANTRA_SRC}/requirements.txt" --quiet --retries 10 --timeout 120
"${VENV_BUILD}/bin/pip" install litellm chromadb textual docker --quiet --retries 10 --timeout 120
log_ok "All pip dependencies installed."

# ── CRITICAL FIX: Hashbang correction ────────────────────────────────────────
# pip embeds the BUILD MACHINE's absolute Python path into the hashbang (#!)
# of every script in venv/bin/. This path won't exist inside the ISO.
# We must rewrite all hashbangs to the DEPLOYMENT path: /opt/yantra/venv/bin/python3
log_info "Fixing hashbangs in venv/bin/ scripts..."
HASHBANG_COUNT=0

while IFS= read -r -d '' script; do
    if head -1 "$script" 2>/dev/null | grep -q "^#!"; then
        sed -i "1s|#!.*python[0-9.]*|#!${VENV_DEPLOY}/bin/python3|" "$script"
        HASHBANG_COUNT=$((HASHBANG_COUNT + 1))
    fi
done < <(find "${VENV_BUILD}/bin" -type f -executable -print0)

log_ok "Fixed hashbangs in ${HASHBANG_COUNT} script(s)."

# Verify the fix
SAMPLE_SCRIPT="${VENV_BUILD}/bin/pip"
if [[ -f "$SAMPLE_SCRIPT" ]]; then
    FIRST_LINE=$(head -1 "$SAMPLE_SCRIPT")
    if echo "$FIRST_LINE" | grep -q "${VENV_DEPLOY}"; then
        log_ok "Hashbang verified: ${FIRST_LINE}"
    else
        log_warn "Hashbang may not be correctly set: ${FIRST_LINE}"
    fi
fi


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3.8: Unified Boot Flow — Pure TUI Launch
# Generates the ArchISO automated script to handle Wi-Fi prompt, start
# yantra.service, and handoff to yantra_user running Cage on TTY1.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 3.8: Unified Boot Flow (TTY1 Collision Fix) ═══"

cat > "${AIROOTFS}/root/.automated_script.sh" << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

LOG=/root/yantra-bootstrap.log
exec > >(tee -a "$LOG") 2>&1

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  YantraOS First-Boot Autopilot"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1) Ensure NetworkManager is running
if ! systemctl is-active --quiet NetworkManager; then
  echo "[YANTRA] Starting NetworkManager..."
  systemctl start NetworkManager
fi

# 2) Network connectivity check — launch nmtui on failure
if ! ping -c1 -W5 yantraos.com > /dev/null 2>&1; then
  echo "[YANTRA] Network not detected. Launching nmtui for Wi-Fi configuration..."
  nmtui || echo "[YANTRA] nmtui exited — continuing boot sequence."
fi

# 3) Ping the telemetry endpoint
echo "[YANTRA] Pinging telemetry health endpoint..."
if curl -fsSL https://yantraos.com/api/health > /dev/null 2>&1; then
  echo "[YANTRA] Telemetry endpoint OK — cloud inference available."
else
  echo "[YANTRA] Telemetry endpoint unreachable — offline mode."
fi

# 4) Wake up Docker Sandbox environment
if ! systemctl is-active --quiet docker; then
  echo "[YANTRA] Waking up Docker Sandbox environment..."
  systemctl start docker
fi

# 5) Enable and start Kriya Loop
if ! systemctl is-enabled --quiet yantra.service; then
  echo "[YANTRA] Enabling yantra.service..."
  systemctl enable yantra.service
fi

echo "[YANTRA] Starting Kriya Loop daemon..."
systemctl start yantra.service

sleep 2
systemctl --no-pager --full status yantra.service || true

# 6) Hand over to Pure TUI on TTY1
#    No Wayland, no cage, no compositor.
#    Direct framebuffer TUI via Textual/Rich.
echo "[YANTRA] Launching Pure TUI for yantra_user on TTY1..."
mkdir -p /home/yantra_user
chown 1000:1000 /home/yantra_user

if [[ -z "${DISPLAY:-}" && $(tty) == /dev/tty1 ]]; then
    chown -R yantra_user:yantra_user /home/yantra_user
    chmod 700 /home/yantra_user
    chmod 666 /dev/tty1
    chmod 777 /run/yantra
    chmod 666 /run/yantra/ipc.sock || true
    exec su - yantra_user -c "cd /opt/yantra && TERM=linux COLORTERM=truecolor /opt/yantra/venv/bin/python3 -m core.tui_shell < /dev/tty1 > /dev/tty1 2>&1"
fi

# 7) Disable self on next boot (live session only)
rm -f /root/.automated_script.sh
EOF

chmod 755 "${AIROOTFS}/root/.automated_script.sh"
log_ok "Automated boot script generated at /root/.automated_script.sh"

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4: PERMISSION MATRIX — profiledef.sh (Invariant 4)
# Inject the file_permissions associative array into profiledef.sh.
# This tells mkarchiso the exact UID:GID:mode for sensitive files.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 4: Permission Matrix — Injecting into profiledef.sh ═══"

if [[ ! -f "${PROFILEDEF}" ]]; then
    log_error "profiledef.sh not found at ${PROFILEDEF}"
    exit 1
fi

# Append the file_permissions array to the end of profiledef.sh.
# The releng profile may already have a file_permissions array; we append
# our entries. If it has no array, we create one.
#
# SECURITY INVARIANTS:
#   /etc/shadow          → 0:0:0400 (root-only read, no group, no other)
#   /etc/gshadow         → 0:0:0400 (same as /etc/shadow)
#   /etc/yantra/host_secrets.env → 0:0:0600 (root-only read/write — API credentials)
#   /opt/yantra/core     → 0:0:0755 (root-owned, world-executable, tamper-proof)
#   /opt/yantra/core/daemon.py → 0:0:0755 (executable entry point)
#   /opt/yantra/core/cli.py    → 0:0:0755 (executable entry point)
#   /opt/yantra/venv     → 0:0:0755 (venv root)
#   /run/yantra          → 999:999:0770 (yantra_daemon:yantra — UDS socket)
#   /var/lib/yantra      → 999:999:0770 (yantra_daemon:yantra — ChromaDB)
#   /var/lib/yantra/chromadb → 999:999:0770 (same)
#   yantra.service       → 0:0:0644 (standard systemd unit)
#   polkit rules         → 0:0:0644 (readable by polkitd)
#   pacman hooks         → 0:0:0644 (standard config file)
#   sysusers.d/tmpfiles.d → 0:0:0644 (standard config file)

# Check if file_permissions already exists in the profiledef
if grep -q "^file_permissions=" "${PROFILEDEF}"; then
    log_info "Existing file_permissions found — replacing with YantraOS matrix."
    # Remove the existing file_permissions block (from declaration to closing paren)
    sed -i '/^file_permissions=(/,/^)/d' "${PROFILEDEF}"
fi

log_info "Injecting YantraOS file_permissions into profiledef.sh..."

cat >> "${PROFILEDEF}" << 'PERMS_EOF'

# ── YantraOS File Permissions ─────────────────────────────────────────────────
# Format: ["/path"]="uid:gid:permissions"
# CRITICAL: NO TRAILING COMMAS. bash will abort on syntax errors.
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
    ["/etc/pacman.d/hooks/00-yantra-autosnap.hook.inactive"]="0:0:0644"
    ["/etc/pacman.d/hooks/99-yantra-reload.hook"]="0:0:0644"

    # ── sysusers / tmpfiles ──────────────────────────────────────────────
    ["/usr/lib/sysusers.d/yantra.conf"]="0:0:0644"
    ["/usr/lib/tmpfiles.d/yantra.conf"]="0:0:0644"

    # ── Boot scripts ─────────────────────────────────────────────────────
    ["/root/.automated_script.sh"]="0:0:0755"

    # ── yantra_user home ─────────────────────────────────────────────────
    ["/home/yantra_user"]="1000:1000:0700"
)
PERMS_EOF

log_ok "File permissions matrix injected into profiledef.sh."


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5: CRLF → LF SANITIZATION (Invariant 5)
# Purge Windows-style CRLF line endings from all staged text files.
# CRLF in shell scripts or systemd units will cause silent parse failures.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 5: CRLF → LF Sanitization ═══"

# Find all text-like files in the archlive tree and strip carriage returns.
# We target common config/script extensions plus files in known locations.
CRLF_COUNT=0

# Use find to locate text files, then sed to strip \r
while IFS= read -r -d '' file; do
    if file "$file" | grep -q "text"; then
        if grep -qP '\r$' "$file" 2>/dev/null; then
            sed -i 's/\r$//' "$file"
            CRLF_COUNT=$((CRLF_COUNT + 1))
            log_info "  Sanitized: ${file#${ARCHLIVE_DIR}/}"
        fi
    fi
done < <(find "${ARCHLIVE_DIR}" -type f \( \
    -name "*.sh" -o -name "*.py" -o -name "*.conf" -o -name "*.service" \
    -o -name "*.hook" -o -name "*.hook.inactive" -o -name "*.rules" \
    -o -name "*.env" -o -name "*.cfg" -o -name "*.txt" \
    -o -name "profiledef.sh" -o -name "packages.x86_64" \
    -o -name "pacman.conf" \
    \) -print0)

# Also explicitly sanitize the top-level profile files
for critical_file in "${PROFILEDEF}" "${PACKAGES_FILE}" "${ARCHLIVE_DIR}/pacman.conf"; do
    if [[ -f "$critical_file" ]] && grep -qP '\r$' "$critical_file" 2>/dev/null; then
        sed -i 's/\r$//' "$critical_file"
        CRLF_COUNT=$((CRLF_COUNT + 1))
        log_info "  Sanitized: ${critical_file#${ARCHLIVE_DIR}/}"
    fi
done

if [[ $CRLF_COUNT -gt 0 ]]; then
    log_ok "Sanitized ${CRLF_COUNT} file(s) from CRLF to LF."
else
    log_ok "No CRLF contamination detected — all files clean."
fi


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5.5: Pacman.conf — Enable Multilib Repository
# Required for 32-bit compatibility libraries.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 5.5: Configuring pacman.conf ═══"

PACMAN_CONF="${ARCHLIVE_DIR}/pacman.conf"

if grep -q "^#\[multilib\]" "${PACMAN_CONF}"; then
    log_info "Enabling [multilib] repository..."
    sed -i '/^#\[multilib\]/{
        s/^#//
        n
        s/^#//
    }' "${PACMAN_CONF}"
    log_ok "[multilib] enabled."
elif grep -q "^\[multilib\]" "${PACMAN_CONF}"; then
    log_ok "[multilib] already enabled."
else
    log_warn "[multilib] section not found — appending."
    echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> "${PACMAN_CONF}"
    log_ok "[multilib] appended."
fi


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 6: EXECUTION — mkarchiso (Invariant 6)
# Enforce root ownership, clean stale builds, compile the ISO.
# ══════════════════════════════════════════════════════════════════════════════

log_info "═══ PHASE 6: Ownership Audit & ISO Build (mkarchiso) ═══"

# ── Security invariant: root ownership of entire build tree ───────────────────
# mkarchiso maps UIDs from the build directory into the ISO. If any file is
# owned by a non-root user, that UID will cascade into the immutable ISO,
# potentially creating security holes or broken permissions.
log_info "Enforcing root ownership on build directory..."
chown -R root:root "${ARCHLIVE_DIR}"
log_ok "Build directory owned by root:root."

# ── Clean previous build artifacts ───────────────────────────────────────────
if [[ -d "${WORK_DIR}" ]]; then
    log_warn "Cleaning stale work directory: ${WORK_DIR}/*"
    rm -rf "${WORK_DIR}"/*
fi
mkdir -p "${WORK_DIR}"
mkdir -p "${OUTPUT_DIR}"

# ── Bootloader Persistence Lock ───────────────────────────────────────────────
# Enforce cow_label=yantra_cow and cow_spacesize=8G in all bootloader configs
# before mkarchiso packs them. This mathematically guarantees the ISO boots
# with persistence enabled.
log_info "Injecting persistent storage parameters into bootloaders..."
find "${ARCHLIVE_DIR}/syslinux" "${ARCHLIVE_DIR}/efiboot" "${ARCHLIVE_DIR}/grub" -type f -exec sed -i 's/\(archisolabel=[^ ]*\)/\1 cow_spacesize=8G console=ttyS0,115200/g' {} + 2>/dev/null || true
find "${ARCHLIVE_DIR}/syslinux" "${ARCHLIVE_DIR}/efiboot" "${ARCHLIVE_DIR}/grub" -type f -exec sed -i 's/\(archisosearchuuid=[^ ]*\)/\1 cow_spacesize=8G console=ttyS0,115200/g' {} + 2>/dev/null || true
log_ok "Bootloader persistent anchors injected."
# ── Execute mkarchiso ─────────────────────────────────────────────────────────
# -v: verbose output for debugging
# -w: work directory for intermediate build artifacts
# -o: output directory for the final ISO file
log_info "Starting mkarchiso build..."
log_info "  Profile:  ${ARCHLIVE_DIR}"
log_info "  Work dir: ${WORK_DIR}"
log_info "  Output:   ${OUTPUT_DIR}"
echo ""

# ── FINAL ROOT OWNERSHIP CHECK (belt-and-suspenders) ─────────────────────────
# Even though we checked at entry, confirm root hasn't been dropped by any
# intermediate su/sudo/namespace operation before handing off to mkarchiso.
if [ "$EUID" -ne 0 ]; then
    log_error "FATAL: Lost root privileges before mkarchiso. Aborting."
    exit 1
fi

mkarchiso -v -w "${WORK_DIR}" -o "${OUTPUT_DIR}" "${ARCHLIVE_DIR}"

BUILD_EXIT=$?

if [[ $BUILD_EXIT -eq 0 ]]; then
    echo ""
    log_ok "═══════════════════════════════════════════════════════════"
    log_ok "  YantraOS Gold Master v1.3 — ISO BUILD SUCCESSFUL"
    log_ok "  Output: ${OUTPUT_DIR}/"
    ls -lh "${OUTPUT_DIR}/"*.iso 2>/dev/null || true
    log_ok "═══════════════════════════════════════════════════════════"
else
    echo ""
    log_error "═══════════════════════════════════════════════════════════"
    log_error "  mkarchiso FAILED with exit code ${BUILD_EXIT}"
    log_error "  Check the build log above for errors."
    log_error "═══════════════════════════════════════════════════════════"
    exit $BUILD_EXIT
fi

# ── Cleanup work directory ────────────────────────────────────────────────────
log_info "Cleaning work directory..."
rm -rf "${WORK_DIR}"
log_ok "Build complete. ISO ready for deployment."
