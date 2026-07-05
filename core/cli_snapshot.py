"""
YantraOS — BTRFS Snapshot CLI (Global Binary Entrypoint)
Target: /opt/yantra/core/cli_snapshot.py
Wrapper: /usr/bin/yantra-snapshot → exec venv python3 this file

Minimal CLI for BTRFS snapshot operations consumed by the Host Executor's
pre-flight gate and prune dispatch.

Subcommands:
  --pre-flight    Create a read-only pre-flight snapshot before any mutation.
  --prune         Delete snapshots older than RETENTION_DAYS (default 7).
  --list          List existing YantraOS snapshots (informational).

Exit codes:
  0 = success
  1 = operational failure (snapshot create/delete failed)
  2 = no BTRFS filesystem detected (non-fatal on overlayfs/ext4)
  3 = usage error

Security:
  • This script is called by the root Host Executor daemon via subprocess
    with explicit argument lists — never shell=True.
  • All subvolume paths are hardcoded constants — no user-supplied paths
    are interpolated into subprocess calls.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("yantra.snapshot")

# ── Constants ─────────────────────────────────────────────────────────────────

# The BTRFS subvolume root where YantraOS snapshots live.
SNAPSHOT_SUBVOL: str = "/@yantra-snapshots"
SNAPSHOT_MOUNT: str = "/mnt/yantra-snapshots"
ROOT_SUBVOL: str = "/@"

# Default retention: keep snapshots for 7 days.
RETENTION_DAYS: int = 7

# BTRFS detection: if the root filesystem is not BTRFS, snapshot operations
# are a no-op (exit 2). This allows the Host Executor to call the binary
# unconditionally without branching on filesystem type.
BTRFS_CHECK_PATH: str = "/"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_btrfs(path: str = BTRFS_CHECK_PATH) -> bool:
    """Check if the given path resides on a BTRFS filesystem."""
    try:
        result = subprocess.run(
            ["/usr/bin/stat", "-f", "--format=%T", path],
            capture_output=True, timeout=10, check=False,
        )
        fs_type = result.stdout.decode("utf-8", errors="replace").strip().lower()
        return "btrfs" in fs_type
    except Exception:
        return False


def _btrfs_cmd(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    """Run a btrfs subcommand with capture and timeout."""
    cmd = ["/usr/bin/btrfs"] + args
    log.info(f"Executing: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def _is_live_iso() -> bool:
    """Detect if running on an archiso Live environment."""
    return Path("/run/archiso/cowspace").exists()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_pre_flight() -> int:
    """
    Create a read-only pre-flight snapshot of the root subvolume.

    On non-BTRFS filesystems (e.g., Live ISO overlayfs), this is a
    successful no-op — the Host Executor interprets exit 0 as "gate passed".
    """
    if _is_live_iso():
        print("LIVE_ISO: Ephemeral overlayfs session — pre-flight snapshot not applicable.")
        print("PRE-FLIGHT: PASSED (ephemeral session, no persistent state to protect)")
        return 0

    if not _is_btrfs():
        print("NO_BTRFS: Root filesystem is not BTRFS — snapshot not applicable.")
        print("PRE-FLIGHT: PASSED (non-BTRFS filesystem)")
        return 0

    # Generate timestamped snapshot name
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    snap_name = f"yantra-preflight-{ts}"
    snap_path = f"{SNAPSHOT_SUBVOL}/{snap_name}"

    # Ensure snapshot subvolume parent exists
    if not Path(SNAPSHOT_MOUNT).exists():
        log.info(f"Creating snapshot mount point: {SNAPSHOT_MOUNT}")
        os.makedirs(SNAPSHOT_MOUNT, exist_ok=True)

    # Create read-only snapshot
    result = _btrfs_cmd([
        "subvolume", "snapshot", "-r",
        ROOT_SUBVOL, snap_path,
    ], timeout=60)

    if result.returncode == 0:
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        print(f"PRE-FLIGHT: PASSED — snapshot created: {snap_path}")
        if stdout:
            print(stdout)
        return 0

    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    print(f"PRE-FLIGHT: FAILED — btrfs snapshot returned exit {result.returncode}", file=sys.stderr)
    if stderr:
        print(stderr, file=sys.stderr)
    return 1


def cmd_prune() -> int:
    """
    Prune YantraOS snapshots older than RETENTION_DAYS.

    On non-BTRFS or Live ISO, this is a successful no-op.
    """
    if _is_live_iso():
        print("LIVE_ISO: Ephemeral session — no snapshots to prune.")
        return 0

    if not _is_btrfs():
        print("NO_BTRFS: Root filesystem is not BTRFS — no snapshots to prune.")
        return 0

    # List subvolumes under the snapshot parent
    result = _btrfs_cmd(["subvolume", "list", "-r", "-s", "/"], timeout=30)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        print(f"PRUNE: Failed to list subvolumes (exit {result.returncode}): {stderr}", file=sys.stderr)
        return 1

    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    if not stdout:
        print("PRUNE: No snapshots found.")
        return 0

    cutoff = time.time() - (RETENTION_DAYS * 86400)
    pruned = 0
    errors = 0

    for line in stdout.splitlines():
        # Parse btrfs subvolume list output for yantra-preflight snapshots
        if "yantra-preflight-" not in line:
            continue

        # Extract the path component
        parts = line.split("path ")
        if len(parts) < 2:
            continue
        snap_path = parts[1].strip()

        # Extract timestamp from snapshot name (yantra-preflight-YYYYMMDD-HHMMSS)
        try:
            name = snap_path.split("/")[-1]
            ts_str = name.replace("yantra-preflight-", "")
            snap_time = time.mktime(time.strptime(ts_str, "%Y%m%d-%H%M%S"))
        except (ValueError, IndexError):
            continue

        if snap_time < cutoff:
            del_result = _btrfs_cmd(["subvolume", "delete", f"/{snap_path}"], timeout=60)
            if del_result.returncode == 0:
                print(f"PRUNED: {snap_path}")
                pruned += 1
            else:
                stderr = del_result.stderr.decode("utf-8", errors="replace").strip()
                print(f"PRUNE ERROR: {snap_path} — {stderr}", file=sys.stderr)
                errors += 1

    print(f"PRUNE: Complete — {pruned} pruned, {errors} errors.")
    return 1 if errors > 0 else 0


def cmd_list() -> int:
    """List existing YantraOS snapshots."""
    if not _is_btrfs():
        print("NO_BTRFS: Root filesystem is not BTRFS.")
        return 2

    result = _btrfs_cmd(["subvolume", "list", "-r", "-s", "/"], timeout=30)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        print(f"LIST: Failed (exit {result.returncode}): {stderr}", file=sys.stderr)
        return 1

    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    count = 0
    for line in stdout.splitlines():
        if "yantra-preflight-" in line:
            print(line)
            count += 1

    if count == 0:
        print("No YantraOS snapshots found.")
    else:
        print(f"\n{count} snapshot(s) total.")
    return 0


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="yantra-snapshot",
        description="YantraOS BTRFS Snapshot Manager",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--pre-flight",
        action="store_true",
        help="Create a read-only pre-flight snapshot before system mutation.",
    )
    group.add_argument(
        "--prune",
        action="store_true",
        help=f"Delete YantraOS snapshots older than {RETENTION_DAYS} days.",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List existing YantraOS snapshots.",
    )

    args = parser.parse_args()

    # Configure logging for CLI usage
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    if args.pre_flight:
        return cmd_pre_flight()
    elif args.prune:
        return cmd_prune()
    elif args.list:
        return cmd_list()

    parser.print_help()
    return 3


if __name__ == "__main__":
    sys.exit(main())
