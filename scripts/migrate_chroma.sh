#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# YantraOS — ChromaDB BTRFS nodatacow Migration Script
# Target: /opt/yantra/scripts/migrate_chroma.sh
#
# Eliminates BTRFS write amplification for RC1→RC3 upgraders.
#
# Problem:
#   chattr +C on an existing directory with files does NOTHING to existing
#   extents. RC1 users who created /var/lib/yantra/chromadb before the +C
#   flag was applied have COW-enabled SQLite WAL files, causing:
#     • 10-50x write amplification on every ChromaDB transaction
#     • Catastrophic BTRFS fragmentation (thousands of extents per file)
#     • Premature SSD wear and I/O latency spikes during REMEMBER phase
#
# Solution:
#   1. Detect if the +C flag is missing on the existing directory.
#   2. Create a new directory WITH +C applied to empty dir (before files).
#   3. Copy all data with --reflink=never (force full data copy, not COW clone).
#   4. Atomic swap: rm old → mv new into place.
#
# This script is idempotent — if +C is already present, it exits cleanly.
# It is invoked by systemd ExecStartPre and blocks daemon startup until
# the I/O boundary is verified.
#
# Must run as root (ExecStartPre runs as the service User unless prefixed
# with +, but chattr requires root — prefix with + in the service file).
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

readonly CHROMA_DIR="/var/lib/yantra/chromadb"
readonly CHROMA_NEW="/var/lib/yantra/chromadb_new"
readonly CHROMA_OWNER="yantra_daemon"
readonly CHROMA_GROUP="yantra"

log() {
    echo "[migrate_chroma] $(date '+%Y-%m-%dT%H:%M:%S') $*"
}

# ── Guard: directory must exist ───────────────────────────────────────────────
if [[ ! -d "${CHROMA_DIR}" ]]; then
    log "INFO: ${CHROMA_DIR} does not exist. Creating with +C attribute."
    mkdir -p "${CHROMA_DIR}"
    chattr +C "${CHROMA_DIR}"
    chown "${CHROMA_OWNER}:${CHROMA_GROUP}" "${CHROMA_DIR}"
    chmod 0750 "${CHROMA_DIR}"
    log "OK: ${CHROMA_DIR} created with nodatacow (+C)."
    exit 0
fi

# ── Check if +C (nodatacow) is already present ───────────────────────────────
if lsattr -d "${CHROMA_DIR}" 2>/dev/null | grep -q 'C'; then
    log "OK: ${CHROMA_DIR} already has nodatacow (+C). No migration needed."
    exit 0
fi

# ── Migration required ───────────────────────────────────────────────────────
log "WARN: ${CHROMA_DIR} is MISSING the nodatacow (+C) attribute."
log "WARN: All existing ChromaDB files have COW-enabled extents."
log "INFO: Starting migration to eliminate BTRFS write amplification..."

# Step 1: Create new directory with +C on the empty dir (before any files)
if [[ -d "${CHROMA_NEW}" ]]; then
    log "WARN: Stale ${CHROMA_NEW} found from previous failed migration. Removing."
    rm -rf "${CHROMA_NEW}"
fi

mkdir -p "${CHROMA_NEW}"
chattr +C "${CHROMA_NEW}"
log "INFO: Created ${CHROMA_NEW} with +C attribute."

# Step 2: Copy data — --reflink=never forces full data copy, not COW clone.
# A COW reflink would preserve the old extents and defeat the purpose.
# -a preserves permissions, timestamps, symlinks, xattrs.
if [[ -n "$(ls -A "${CHROMA_DIR}" 2>/dev/null)" ]]; then
    log "INFO: Copying data from ${CHROMA_DIR} to ${CHROMA_NEW} (reflink=never)..."
    cp --reflink=never -a "${CHROMA_DIR}/"* "${CHROMA_NEW}/"
    log "INFO: Data copy complete."
else
    log "INFO: ${CHROMA_DIR} is empty. No data to migrate."
fi

# Step 3: Atomic swap
log "INFO: Removing old directory..."
rm -rf "${CHROMA_DIR}"

log "INFO: Moving new directory into place..."
mv "${CHROMA_NEW}" "${CHROMA_DIR}"

# Step 4: Ensure ownership
chown -R "${CHROMA_OWNER}:${CHROMA_GROUP}" "${CHROMA_DIR}"
chmod 0750 "${CHROMA_DIR}"

# Step 5: Verify
if lsattr -d "${CHROMA_DIR}" 2>/dev/null | grep -q 'C'; then
    log "OK: Migration complete. ${CHROMA_DIR} now has nodatacow (+C)."
    log "OK: All new file extents will bypass COW — write amplification eliminated."
    exit 0
else
    log "FATAL: Migration failed — +C attribute not present after swap."
    log "FATAL: Manual intervention required."
    exit 1
fi
