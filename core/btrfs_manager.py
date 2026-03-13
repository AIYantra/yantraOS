"""
YantraOS — BTRFS Snapshot Manager
Target: /opt/yantra/core/btrfs_manager.py
Milestone 4, Tasks 4.1 & 4.2

Orchestrates BTRFS subvolume operations for atomic system snapshots and
rollback. All privileged commands are executed via `pkexec` — privilege
escalation is authorized exclusively by the Polkit rule in
/etc/polkit-1/rules.d/50-yantra-btrfs.rules (Milestone 1, Task 1.3).

The daemon user (yantra_daemon) has NO direct root access. Every invocation
passes through:
  yantra_daemon → pkexec → polkitd → 50-yantra-btrfs.rules → /usr/bin/btrfs

Security invariants:
  • Snapshot names are sanitized to [a-zA-Z0-9_] only — no shell injection.
  • Commands are passed as explicit list arguments to subprocess.run — no
    shell=True, no string interpolation into shell commands.
  • subprocess.run(check=True, capture_output=True) — failures are caught
    and propagated as structured error objects for the Kriya Loop.
  • Snapshot IDs are validated as pure numeric integers before use in
    set-default commands.

BTRFS layout assumption:
  Active root:  / (subvol=@)
  Snapshots:    /@snapshots/yantra_snap_<timestamp>
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger("yantra.btrfs_manager")

# ── Constants ─────────────────────────────────────────────────────────────────

BTRFS_BIN: str = "/usr/bin/btrfs"
PKEXEC_BIN: str = "/usr/bin/pkexec"

# Snapshot directory — must be a BTRFS subvolume mount point.
SNAPSHOT_ROOT: str = "/@snapshots"

# Snapshot name prefix — all daemon-created snapshots start with this.
SNAPSHOT_PREFIX: str = "yantra_snap_"

# Active root subvolume path (the current booted filesystem root).
ACTIVE_ROOT: str = "/"

# Maximum age for auto-pruning old snapshots (7 days in seconds).
PRUNE_MAX_AGE_SECS: int = 7 * 24 * 60 * 60

# Input sanitization regex — ONLY alphanumeric characters and underscores.
# This mathematically eliminates shell injection, path traversal, and
# null-byte attacks against the snapshot name.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")

# Snapshot ID validation — must be a pure numeric integer.
_NUMERIC_RE = re.compile(r"^[0-9]+$")


def _build_btrfs_cmd(*args: str) -> list[str]:
    """
    Build a btrfs command array with UID-aware prefix selection.

    When running as root (UID 0) — e.g., from a Pacman libalpm hook —
    invoke /usr/bin/btrfs directly. No pkexec overhead, no unnecessary
    polkitd roundtrip.

    When running as yantra_daemon (non-root), prefix with pkexec to
    escalate via the polkit rule in 50-yantra-btrfs.rules.

    Args:
        *args: btrfs subcommand arguments (e.g., "subvolume", "snapshot", "/").

    Returns:
        Command array ready for subprocess.run().
    """
    if os.getuid() == 0:
        return [BTRFS_BIN, *args]
    return [PKEXEC_BIN, BTRFS_BIN, *args]


# ── Data Types ────────────────────────────────────────────────────────────────


class SnapshotOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    VALIDATION_ERROR = "validation_error"
    BTRFS_NOT_AVAILABLE = "btrfs_not_available"


@dataclass
class SnapshotResult:
    """Structured result from a BTRFS operation."""
    outcome: SnapshotOutcome
    snapshot_name: str = ""
    snapshot_path: str = ""
    message: str = ""
    stdout: str = ""
    stderr: str = ""
    duration_secs: float = 0.0


@dataclass
class SnapshotInfo:
    """Metadata for a discovered snapshot."""
    name: str
    path: str
    timestamp: float = 0.0  # Extracted from the name suffix
    subvol_id: int = -1


@dataclass
class RollbackResult:
    """Structured result from a rollback operation."""
    outcome: SnapshotOutcome
    target_snapshot: str = ""
    subvol_id: int = -1
    message: str = ""
    reboot_initiated: bool = False


# ── Input Sanitization ────────────────────────────────────────────────────────


def _sanitize_name(name: str) -> str:
    """
    Aggressively sanitize a snapshot name component.

    Only allows [a-zA-Z0-9_]. Any other character raises ValueError.
    This prevents:
      • Shell injection (;, |, &, $, `, etc.)
      • Path traversal (../, /, ~)
      • Null byte injection (\x00)
      • Unicode-based bypass attacks

    Args:
        name: The raw name component to sanitize.

    Returns:
        The validated name (unchanged if valid).

    Raises:
        ValueError: If the name contains any disallowed characters.
    """
    if not name:
        raise ValueError("Snapshot name cannot be empty.")
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"SECURITY: Snapshot name '{name}' contains disallowed characters. "
            "Only [a-zA-Z0-9_] are permitted."
        )
    if len(name) > 128:
        raise ValueError(
            f"Snapshot name exceeds 128 characters ({len(name)}). "
            "Possible buffer overflow attempt."
        )
    return name


def _validate_subvol_id(raw_id: str) -> int:
    """
    Strict type-check: verify that a subvolume ID is purely numeric.

    This prevents injection of arbitrary arguments into the
    `btrfs subvolume set-default <id> /` command.

    Args:
        raw_id: The raw string output from `btrfs inspect-internal rootid`.

    Returns:
        The validated integer subvolume ID.

    Raises:
        ValueError: If the string is not a pure integer.
    """
    cleaned = raw_id.strip()
    if not _NUMERIC_RE.match(cleaned):
        raise ValueError(
            f"SECURITY: Subvolume ID '{cleaned}' is not a pure integer. "
            "Refusing to inject into set-default command."
        )
    subvol_id = int(cleaned)
    if subvol_id <= 0:
        raise ValueError(
            f"Subvolume ID must be positive, got {subvol_id}."
        )
    return subvol_id


# ── Preflight ─────────────────────────────────────────────────────────────────


def is_btrfs_available() -> bool:
    """
    Verify that the btrfs binary exists and the root filesystem is BTRFS.
    Called during daemon bootstrap to determine if snapshot operations
    are possible on this system.
    """
    if not os.path.isfile(BTRFS_BIN):
        log.warning(f"> BTRFS: Binary not found at {BTRFS_BIN}.")
        return False

    try:
        result = subprocess.run(
            [BTRFS_BIN, "filesystem", "show", "/"],
            capture_output=True, timeout=10, check=False,
        )
        if result.returncode == 0:
            log.info("> BTRFS: Root filesystem confirmed as BTRFS.")
            return True
        else:
            log.warning(
                f"> BTRFS: Root is not a BTRFS filesystem "
                f"(exit={result.returncode})."
            )
            return False
    except FileNotFoundError:
        log.warning("> BTRFS: Binary not found.")
        return False
    except subprocess.TimeoutExpired:
        log.warning("> BTRFS: Filesystem check timed out.")
        return False
    except Exception as exc:
        log.warning(f"> BTRFS: Preflight check failed: {exc}")
        return False


def _ensure_snapshot_root() -> bool:
    """Ensure the /@snapshots subvolume exists.

    Uses `btrfs subvolume create` with UID-aware prefix selection.
    When running as root (pacman hook), invokes btrfs directly.
    When running as yantra_daemon, escalates via pkexec.
    """
    snapshot_dir = Path(SNAPSHOT_ROOT)
    if snapshot_dir.exists():
        return True
    try:
        subprocess.run(
            _build_btrfs_cmd("subvolume", "create", SNAPSHOT_ROOT),
            check=True, capture_output=True, timeout=15,
        )
        log.info(f"> BTRFS: Created snapshot subvolume {SNAPSHOT_ROOT}")
        return True
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip() if exc.stderr else ""
        log.error(f"> BTRFS: Failed to create {SNAPSHOT_ROOT}: {stderr}")
        return False
    except Exception as exc:
        log.error(f"> BTRFS: Failed to create snapshot root: {exc}")
        return False


# ── Task 4.1: Snapshot Creation ───────────────────────────────────────────────


def create_snapshot(label: str = "") -> SnapshotResult:
    """
    Create an atomic BTRFS snapshot of the active root filesystem.

    The snapshot is named: yantra_snap_<label>_<timestamp>
    The label is sanitized to [a-zA-Z0-9_] only.

    Execution path:
        pkexec /usr/bin/btrfs subvolume snapshot / /@snapshots/yantra_snap_<name>

    pkexec delegates privilege escalation to the Polkit rule in
    50-yantra-btrfs.rules, which authorizes yantra_daemon for
    /usr/bin/btrfs without a password prompt.

    Args:
        label: Optional human-readable label for the snapshot (e.g., "pacman_pre").
               Sanitized to alphanumeric + underscore only.

    Returns:
        SnapshotResult with outcome, path, and timing.
    """
    t_start = time.monotonic()

    # ── Build sanitized snapshot name ─────────────────────────────────
    timestamp = str(int(time.time()))

    if label:
        try:
            safe_label = _sanitize_name(label)
        except ValueError as exc:
            return SnapshotResult(
                outcome=SnapshotOutcome.VALIDATION_ERROR,
                message=str(exc),
            )
        snap_name = f"{SNAPSHOT_PREFIX}{safe_label}_{timestamp}"
    else:
        snap_name = f"{SNAPSHOT_PREFIX}{timestamp}"

    snap_path = f"{SNAPSHOT_ROOT}/{snap_name}"

    # ── Preflight ─────────────────────────────────────────────────────
    if not is_btrfs_available():
        return SnapshotResult(
            outcome=SnapshotOutcome.BTRFS_NOT_AVAILABLE,
            snapshot_name=snap_name,
            message="BTRFS is not available on this system.",
        )

    _ensure_snapshot_root()

    # ── Execute snapshot command ──────────────────────────────────────
    cmd = _build_btrfs_cmd("subvolume", "snapshot", ACTIVE_ROOT, snap_path)

    log.info(f"> BTRFS: Creating snapshot — {snap_name}")
    log.debug(f"> BTRFS: Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=60,
        )

        elapsed = time.monotonic() - t_start
        stdout = result.stdout.decode("utf-8", errors="replace").strip()

        log.info(
            f"> BTRFS: Snapshot created — {snap_name} "
            f"({elapsed:.2f}s)"
        )

        return SnapshotResult(
            outcome=SnapshotOutcome.SUCCESS,
            snapshot_name=snap_name,
            snapshot_path=snap_path,
            message=f"Snapshot created successfully: {snap_path}",
            stdout=stdout,
            duration_secs=round(elapsed, 3),
        )

    except subprocess.CalledProcessError as exc:
        elapsed = time.monotonic() - t_start
        stderr = exc.stderr.decode("utf-8", errors="replace").strip() if exc.stderr else ""
        stdout = exc.stdout.decode("utf-8", errors="replace").strip() if exc.stdout else ""

        log.error(
            f"> BTRFS: Snapshot FAILED — {snap_name} "
            f"(exit={exc.returncode}, {elapsed:.2f}s)\n"
            f"  stderr: {stderr}"
        )

        return SnapshotResult(
            outcome=SnapshotOutcome.FAILURE,
            snapshot_name=snap_name,
            snapshot_path=snap_path,
            message=f"btrfs snapshot failed (exit={exc.returncode}): {stderr}",
            stdout=stdout,
            stderr=stderr,
            duration_secs=round(elapsed, 3),
        )

    except subprocess.TimeoutExpired:
        return SnapshotResult(
            outcome=SnapshotOutcome.FAILURE,
            snapshot_name=snap_name,
            message="btrfs snapshot timed out after 60 seconds.",
        )

    except Exception as exc:
        return SnapshotResult(
            outcome=SnapshotOutcome.FAILURE,
            snapshot_name=snap_name,
            message=f"Unexpected error: {type(exc).__name__}: {exc}",
        )


# ── Task 4.2: Rollback & Default Subvolume Manipulation ──────────────────────


def get_snapshot_id(snapshot_path: str) -> int:
    """
    Retrieve the unique numeric subvolume ID (rootid) of a snapshot.

    Executes:
        pkexec /usr/bin/btrfs inspect-internal rootid /@snapshots/<target>

    Args:
        snapshot_path: Absolute path to the snapshot subvolume.

    Returns:
        The integer subvolume ID.

    Raises:
        RuntimeError: If the command fails or the ID is not numeric.
    """
    cmd = _build_btrfs_cmd("inspect-internal", "rootid", snapshot_path)

    log.info(f"> BTRFS: Querying rootid for {snapshot_path}")

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=15,
        )
        raw_id = result.stdout.decode("utf-8", errors="replace").strip()
        subvol_id = _validate_subvol_id(raw_id)
        log.info(f"> BTRFS: Snapshot {snapshot_path} has rootid={subvol_id}")
        return subvol_id

    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip() if exc.stderr else ""
        raise RuntimeError(
            f"Failed to get rootid for {snapshot_path} "
            f"(exit={exc.returncode}): {stderr}"
        ) from exc

    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def set_default_subvolume(subvol_id: int) -> None:
    """
    Set the default BTRFS subvolume to the specified ID.

    After this, the next boot will mount the snapshot as /.

    Executes:
        pkexec /usr/bin/btrfs subvolume set-default <id> /

    Args:
        subvol_id: The numeric subvolume ID (must be a positive integer).

    Raises:
        ValueError: If subvol_id is not a positive integer.
        RuntimeError: If the btrfs command fails.
    """
    # Strict type-check — defense in depth beyond _validate_subvol_id
    if not isinstance(subvol_id, int) or subvol_id <= 0:
        raise ValueError(
            f"SECURITY: subvol_id must be a positive integer, "
            f"got {type(subvol_id).__name__}={subvol_id}"
        )

    cmd = _build_btrfs_cmd("subvolume", "set-default", str(subvol_id), ACTIVE_ROOT)

    log.info(f"> BTRFS: Setting default subvolume to ID {subvol_id}")

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=15,
        )
        log.info(
            f"> BTRFS: Default subvolume set to {subvol_id}. "
            "Next boot will mount this snapshot as /."
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip() if exc.stderr else ""
        raise RuntimeError(
            f"Failed to set default subvolume to {subvol_id} "
            f"(exit={exc.returncode}): {stderr}"
        ) from exc


def rollback_to_snapshot(snapshot_name: str, *, reboot: bool = True) -> RollbackResult:
    """
    Execute a full system rollback to a named snapshot.

    Steps:
      1. Sanitize the snapshot name (aggressive input validation).
      2. Resolve the full path: /@snapshots/<snapshot_name>.
      3. Query the rootid via `btrfs inspect-internal rootid`.
      4. Set the default subvolume via `btrfs subvolume set-default`.
      5. Optionally initiate a system reboot.

    After reboot, the system will mount the snapshot as / instead of @.

    Args:
        snapshot_name: The name of the snapshot to roll back to.
        reboot: Whether to initiate an immediate system reboot.

    Returns:
        RollbackResult with outcome and subvolume ID.
    """
    # ── Step 1: Sanitize ──────────────────────────────────────────────
    try:
        safe_name = _sanitize_name(snapshot_name)
    except ValueError as exc:
        return RollbackResult(
            outcome=SnapshotOutcome.VALIDATION_ERROR,
            target_snapshot=snapshot_name,
            message=str(exc),
        )

    snap_path = f"{SNAPSHOT_ROOT}/{safe_name}"

    # ── Step 2: Verify snapshot exists ────────────────────────────────
    if not Path(snap_path).exists():
        return RollbackResult(
            outcome=SnapshotOutcome.FAILURE,
            target_snapshot=safe_name,
            message=f"Snapshot not found: {snap_path}",
        )

    # ── Step 3: Get rootid ────────────────────────────────────────────
    try:
        subvol_id = get_snapshot_id(snap_path)
    except RuntimeError as exc:
        return RollbackResult(
            outcome=SnapshotOutcome.FAILURE,
            target_snapshot=safe_name,
            message=f"Failed to resolve snapshot ID: {exc}",
        )

    # ── Step 4: Set default subvolume ─────────────────────────────────
    try:
        set_default_subvolume(subvol_id)
    except (ValueError, RuntimeError) as exc:
        return RollbackResult(
            outcome=SnapshotOutcome.FAILURE,
            target_snapshot=safe_name,
            subvol_id=subvol_id,
            message=f"Failed to set default subvolume: {exc}",
        )

    log.info(
        f"> BTRFS: Rollback complete — default set to {safe_name} "
        f"(subvol_id={subvol_id})"
    )

    # ── Step 5: Reboot ────────────────────────────────────────────────
    reboot_initiated = False
    if reboot:
        log.info("> BTRFS: Initiating system reboot for rollback activation...")
        try:
            subprocess.run(
                ["/usr/bin/systemctl", "reboot"],
                check=True, timeout=10,
            )
            reboot_initiated = True
        except Exception as exc:
            log.error(f"> BTRFS: Reboot command failed: {exc}")

    return RollbackResult(
        outcome=SnapshotOutcome.SUCCESS,
        target_snapshot=safe_name,
        subvol_id=subvol_id,
        message=(
            f"Rollback to {safe_name} (id={subvol_id}) complete. "
            f"{'Reboot initiated.' if reboot_initiated else 'Manual reboot required.'}"
        ),
        reboot_initiated=reboot_initiated,
    )


# ── Snapshot Listing & Pruning ────────────────────────────────────────────────


def list_snapshots() -> list[SnapshotInfo]:
    """
    List all YantraOS snapshots in /@snapshots/.

    Returns snapshots sorted by timestamp (newest first).
    Only returns snapshots matching the yantra_snap_ prefix.
    """
    snapshots: list[SnapshotInfo] = []
    snapshot_dir = Path(SNAPSHOT_ROOT)

    if not snapshot_dir.exists():
        log.info(f"> BTRFS: Snapshot directory {SNAPSHOT_ROOT} does not exist.")
        return snapshots

    for entry in snapshot_dir.iterdir():
        if not entry.name.startswith(SNAPSHOT_PREFIX):
            continue

        # Extract timestamp from the name suffix
        # Format: yantra_snap_<label>_<timestamp> or yantra_snap_<timestamp>
        parts = entry.name.split("_")
        ts = 0.0
        if parts:
            try:
                ts = float(parts[-1])
            except ValueError:
                pass

        snapshots.append(SnapshotInfo(
            name=entry.name,
            path=str(entry),
            timestamp=ts,
        ))

    # Sort newest first
    snapshots.sort(key=lambda s: s.timestamp, reverse=True)
    log.info(f"> BTRFS: Found {len(snapshots)} snapshot(s).")
    return snapshots


def prune_old_snapshots(max_age_secs: int = PRUNE_MAX_AGE_SECS) -> int:
    """
    Delete snapshots older than max_age_secs (default: 7 days).

    Executes:
        pkexec /usr/bin/btrfs subvolume delete /@snapshots/<old_snap>

    Returns the number of snapshots pruned.
    """
    now = time.time()
    pruned = 0
    snapshots = list_snapshots()

    for snap in snapshots:
        if snap.timestamp <= 0:
            continue  # Skip snapshots without parseable timestamps
        age = now - snap.timestamp
        if age > max_age_secs:
            log.info(
                f"> BTRFS: Pruning old snapshot — {snap.name} "
                f"(age={age / 86400:.1f} days)"
            )
            try:
                subprocess.run(
                    _build_btrfs_cmd("subvolume", "delete", snap.path),
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
                pruned += 1
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
                log.warning(
                    f"> BTRFS: Failed to prune {snap.name}: {stderr}"
                )

    if pruned:
        log.info(f"> BTRFS: Pruned {pruned} snapshot(s) older than {max_age_secs // 86400} days.")
    return pruned


# ── Kriya Loop Integration ────────────────────────────────────────────────────


def create_snapshot_for_kriya(label: str = "") -> dict[str, Any]:
    """
    Create a BTRFS snapshot and return a structured alert for the Kriya Loop.

    Wraps create_snapshot() and inspects the result. On failure, dispatches
    a critical system alert via push_log_event() so the operator sees it
    in the TUI ThoughtStream in real-time.

    Returns:
        A dict compatible with KriyaState.pending_actions format:
        {"type": str, "reason": str, "priority": str, "snapshot_result": dict}
    """
    from .ipc_server import push_log_event

    result = create_snapshot(label)

    alert: dict[str, Any] = {
        "type": "btrfs_snapshot",
        "reason": result.message,
        "priority": "LOW",
        "snapshot_result": {
            "outcome": result.outcome.value,
            "name": result.snapshot_name,
            "path": result.snapshot_path,
            "duration_secs": result.duration_secs,
        },
    }

    if result.outcome == SnapshotOutcome.SUCCESS:
        msg = (
            f"> BTRFS: Snapshot {result.snapshot_name} created "
            f"({result.duration_secs:.2f}s)"
        )
        log.info(msg)
        push_log_event(msg)
        alert["priority"] = "LOW"
    else:
        # ── Critical alert: feed failure into cognitive pipeline ────────
        err_msg = (
            f"> ERROR: BTRFS snapshot FAILED — "
            f"{result.outcome.value}: {result.message}"
        )
        if result.stderr:
            err_msg += f" | stderr: {result.stderr[:500]}"

        log.error(err_msg)
        push_log_event(err_msg)
        alert["priority"] = "CRITICAL"
        alert["type"] = "btrfs_snapshot_failure"

    return alert
