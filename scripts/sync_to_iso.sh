#!/usr/bin/env bash
# sync_to_iso.sh - Enforces synchronization between dev env and ISO overlay safely
set -euo pipefail

echo "=== YantraOS ISO Sync Pre-Flight ==="

# 1. Project Root Check
if [[ ! -d "archlive" ]] || [[ ! -d "core" ]]; then
    echo "FATAL: This script must be executed from the project root."
    exit 1
fi

# 2. Secret File Check (Git Index)
echo "Running git index secret audit..."
if git ls-files | grep -iE '\.env|\.pem|\.key'; then
    echo "FATAL: Tracked secret files detected in Git index! Aborting sync."
    exit 1
fi

DEST="archlive/airootfs/opt/yantra"
mkdir -p "$DEST"

echo "Syncing core/ to ISO overlay (Amnesia Protocol enforced)..."
rsync -av --delete \
    --exclude='.env*' \
    --exclude='*.pem' \
    --exclude='*.key' \
    --exclude='__pycache__/' \
    --exclude='*.json' \
    core/ "$DEST/core/"

echo "Syncing deploy/ to ISO overlay (Amnesia Protocol enforced)..."
rsync -av --delete \
    --exclude='.env*' \
    --exclude='*.pem' \
    --exclude='*.key' \
    --exclude='__pycache__/' \
    --exclude='*.json' \
    deploy/ "$DEST/deploy/"

if [[ -f "config.yaml" ]]; then
    echo "Syncing config.yaml..."
    rsync -av config.yaml "$DEST/config.yaml"
else
    echo "No config.yaml found in project root, skipping."
fi

echo "=== Sync Complete ==="
