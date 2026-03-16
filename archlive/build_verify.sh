#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# YantraOS — ISO Verification Protocol
# Target: archlive/build_verify.sh
#
# Post-build static analysis of the compiled ISO image.
# Validates the presence of critical structural assets inside the squashfs
# and generates a SHA-256 checksum for secure distribution.
#
# Usage:
#   bash build_verify.sh /path/to/YantraOS-YYYY.MM.DD-x86_64.iso
#
# Exit codes:
#   0 — All checks passed
#   1 — One or more critical assets missing or ISO not found
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Color output helpers ──────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[PASS]${NC}  $*"; }
log_fail()  { echo -e "${RED}[FAIL]${NC}  $*" >&2; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

# ── Input validation ─────────────────────────────────────────────────────────

ISO="${1:-}"

if [[ -z "$ISO" ]]; then
    log_fail "Usage: $0 <path-to-iso>"
    exit 1
fi

if [[ ! -f "$ISO" ]]; then
    log_fail "ISO file not found: $ISO"
    exit 1
fi

log_info "══════════════════════════════════════════════════════════════"
log_info "  YantraOS ISO Verification Protocol"
log_info "  Target: $ISO"
log_info "══════════════════════════════════════════════════════════════"

# ── Extract ISO file listing ─────────────────────────────────────────────────
# bsdtar can read ISO 9660 images directly and list their contents.
# We capture the full listing once and grep against it for each asset.

log_info "Extracting ISO file listing via bsdtar..."
ISO_LISTING=$(bsdtar -tf "$ISO" 2>/dev/null) || {
    log_fail "bsdtar failed to read ISO. Is libarchive/bsdtar installed?"
    exit 1
}
log_ok "ISO listing extracted ($(echo "$ISO_LISTING" | wc -l) entries)."

# ── Critical Asset Verification ──────────────────────────────────────────────
# Each asset is a structural invariant. If any is missing, the ISO is
# geometrically broken and must not be distributed.

FAILURES=0

# Asset 1: NVIDIA DKMS driver module
log_info "Checking for nvidia-dkms..."
if echo "$ISO_LISTING" | grep -qi "nvidia-dkms"; then
    log_ok "nvidia-dkms: FOUND in ISO manifest."
else
    log_fail "nvidia-dkms: NOT FOUND in ISO manifest."
    FAILURES=$((FAILURES + 1))
fi

# Asset 2: Yantra systemd service unit
log_info "Checking for yantra.service..."
if echo "$ISO_LISTING" | grep -q "yantra.service"; then
    log_ok "yantra.service: FOUND in ISO manifest."
else
    log_fail "yantra.service: NOT FOUND in ISO manifest."
    FAILURES=$((FAILURES + 1))
fi

# Asset 3: First-boot autopilot script
log_info "Checking for .automated_script.sh..."
if echo "$ISO_LISTING" | grep -q ".automated_script.sh"; then
    log_ok ".automated_script.sh: FOUND in ISO manifest."
else
    log_fail ".automated_script.sh: NOT FOUND in ISO manifest."
    FAILURES=$((FAILURES + 1))
fi

# ── Verdict ──────────────────────────────────────────────────────────────────

echo ""
if [[ $FAILURES -gt 0 ]]; then
    log_fail "══════════════════════════════════════════════════════════════"
    log_fail "  VERIFICATION FAILED — $FAILURES critical asset(s) missing."
    log_fail "  This ISO is NOT safe for distribution."
    log_fail "══════════════════════════════════════════════════════════════"
    exit 1
fi

log_ok "All critical assets verified."

# ── SHA-256 Checksum Generation ──────────────────────────────────────────────
# Generate a cryptographic hash for secure distribution and integrity
# verification on the deployment target.

log_info "Generating SHA-256 checksum..."
sha256sum "$ISO" > "${ISO}.sha256"
log_ok "Checksum written to: ${ISO}.sha256"
cat "${ISO}.sha256"

echo ""
log_ok "══════════════════════════════════════════════════════════════"
log_ok "  YantraOS ISO Verification — ALL CHECKS PASSED"
log_ok "══════════════════════════════════════════════════════════════"
