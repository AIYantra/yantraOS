#!/usr/bin/env bash
# scripts/purify_matrix.sh - YantraOS Purification Protocol
# Prepares the repository for Public Version 1.0 Alpha release.

set -euo pipefail

# ANSI Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}▶ Initiating YantraOS Geometric Purification...${NC}"

# 1. Geometric Folder Structure Enforcements
echo -e "${BLUE}▶ Enforcing strict directory hierarchy...${NC}"

mkdir -p core archlive cloud deploy/systemd scripts webhud

# Move files to core/
for f in engine.py hybrid_router.py host_executor.py cli_snapshot.py; do
    [ -f "$f" ] && mv -v "$f" core/ || true
done

# Move files to archlive/
for f in forge_sovereign_iso.sh profiledef.sh packages.x86_64; do
    [ -f "$f" ] && mv -v "$f" archlive/ || true
done

# Move files to cloud/
for f in forge_azure_vhd.sh azure_vm_deploy.azcli; do
    [ -f "$f" ] && mv -v "$f" cloud/ || true
done

# Move files to deploy/systemd/
for f in yantra.service yantra-host-executor.service; do
    [ -f "$f" ] && mv -v "$f" deploy/systemd/ || true
done

# Move files to scripts/
for f in spin_yantra_matrix.sh; do
    [ -f "$f" ] && mv -v "$f" scripts/ || true
done

echo -e "${GREEN}✓ Geometric structure enforced.${NC}"

# 2. Cleanup operations
echo -e "${BLUE}▶ Wiping caches and telemetry logs...${NC}"

# Wipe __pycache__
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Wipe local telemetry logs
rm -f *.log
find . -type f -name "*.log" -exec rm -f {} + 2>/dev/null || true

# Purge loose keys and environment variables in root if any
rm -f *.pem *.pub *.env 2>/dev/null || true

echo -e "${GREEN}✓ Caches, logs, and root secrets wiped.${NC}"

# Summary
echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  YantraOS Matrix is sterile and ready for push.${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
