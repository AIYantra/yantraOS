"""
YantraOS — CLI Entry Point
Target: /opt/yantra/core/cli.py
Milestone 4, Task 4.3 (supporting module)

Provides a command-line interface for YantraOS administrative operations.
This module is invoked directly by external systems such as Pacman hooks,
systemd ExecStartPre, or manual operator commands.

Primary use case:
  /usr/bin/python3 /opt/yantra/core/cli.py --create-snapshot "pacman_pre"

This is called by the Pacman pre-transaction hook (00-yantra-autosnap.hook)
to create an atomic BTRFS snapshot before any package install, upgrade,
or removal operation. If the snapshot fails, the hook returns exit code 1,
and libalpm aborts the entire transaction (due to AbortOnFail).
"""

from __future__ import annotations

import argparse
import logging
import sys

log = logging.getLogger("yantra.cli")


def _setup_logging() -> None:
    """Configure logging for CLI invocations (typically from pacman hooks)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _cmd_create_snapshot(args: argparse.Namespace) -> int:
    """
    Handle `--create-snapshot <label>`.

    Returns:
        0 on success, 1 on failure.
        The exit code is critical — the Pacman hook uses AbortOnFail,
        so exit(1) aborts the entire package transaction.
    """
    from .btrfs_manager import create_snapshot, SnapshotOutcome

    label = args.create_snapshot
    log.info(f"> CLI: Creating snapshot with label '{label}'...")

    result = create_snapshot(label=label)

    if result.outcome == SnapshotOutcome.SUCCESS:
        log.info(f"> CLI: ✓ {result.message}")
        print(f"[yantra] Snapshot created: {result.snapshot_path}")
        return 0
    else:
        log.error(f"> CLI: ✗ {result.message}")
        print(f"[yantra] SNAPSHOT FAILED: {result.message}", file=sys.stderr)
        if result.stderr:
            print(f"[yantra] stderr: {result.stderr}", file=sys.stderr)
        return 1


def _cmd_rollback(args: argparse.Namespace) -> int:
    """
    Handle `--rollback <snapshot_name>`.

    Returns:
        0 on success, 1 on failure.
    """
    from .btrfs_manager import rollback_to_snapshot, SnapshotOutcome

    name = args.rollback
    no_reboot = args.no_reboot
    log.info(f"> CLI: Rolling back to snapshot '{name}'...")

    result = rollback_to_snapshot(name, reboot=not no_reboot)

    if result.outcome == SnapshotOutcome.SUCCESS:
        log.info(f"> CLI: ✓ {result.message}")
        print(f"[yantra] {result.message}")
        return 0
    else:
        log.error(f"> CLI: ✗ {result.message}")
        print(f"[yantra] ROLLBACK FAILED: {result.message}", file=sys.stderr)
        return 1


def _cmd_list_snapshots(args: argparse.Namespace) -> int:
    """
    Handle `--list-snapshots`.

    Returns:
        0 always (informational).
    """
    from .btrfs_manager import list_snapshots
    import time

    snapshots = list_snapshots()

    if not snapshots:
        print("[yantra] No snapshots found.")
        return 0

    print(f"[yantra] {len(snapshots)} snapshot(s):\n")
    print(f"  {'Name':<50} {'Age':>12}")
    print(f"  {'─' * 50} {'─' * 12}")

    now = time.time()
    for snap in snapshots:
        if snap.timestamp > 0:
            age_secs = now - snap.timestamp
            if age_secs < 3600:
                age_str = f"{age_secs / 60:.0f}m ago"
            elif age_secs < 86400:
                age_str = f"{age_secs / 3600:.1f}h ago"
            else:
                age_str = f"{age_secs / 86400:.1f}d ago"
        else:
            age_str = "unknown"
        print(f"  {snap.name:<50} {age_str:>12}")

    return 0


def _cmd_prune(args: argparse.Namespace) -> int:
    """
    Handle `--prune`.

    Returns:
        0 always.
    """
    from .btrfs_manager import prune_old_snapshots

    pruned = prune_old_snapshots()
    print(f"[yantra] Pruned {pruned} old snapshot(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """
    Parse CLI arguments and dispatch to the appropriate handler.

    Exit codes:
        0 — Success
        1 — Operation failed (triggers AbortOnFail in pacman hooks)
        2 — Invalid arguments
    """
    _setup_logging()

    parser = argparse.ArgumentParser(
        prog="yantra-cli",
        description="YantraOS — System management CLI",
    )

    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument(
        "--create-snapshot",
        metavar="LABEL",
        help="Create a BTRFS snapshot with the given label (e.g., 'pacman_pre').",
    )

    group.add_argument(
        "--rollback",
        metavar="SNAPSHOT_NAME",
        help="Roll back the system to the named snapshot.",
    )

    group.add_argument(
        "--list-snapshots",
        action="store_true",
        help="List all YantraOS BTRFS snapshots.",
    )

    group.add_argument(
        "--prune",
        action="store_true",
        help="Delete snapshots older than 7 days.",
    )

    parser.add_argument(
        "--no-reboot",
        action="store_true",
        default=False,
        help="Skip automatic reboot after rollback (use with --rollback).",
    )

    args = parser.parse_args(argv)

    if args.create_snapshot:
        return _cmd_create_snapshot(args)
    elif args.rollback:
        return _cmd_rollback(args)
    elif args.list_snapshots:
        return _cmd_list_snapshots(args)
    elif args.prune:
        return _cmd_prune(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
