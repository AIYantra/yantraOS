#!/usr/bin/env python3
"""
YantraOS — Status CLI
Target: /opt/yantra/core/cli_status.py
Brutalist operator interface for YantraOS Headless MVP.
"""

import json
import os
import subprocess
import sys
import textwrap

AUDIT_LOG_PATH = "/var/log/yantra/audit.jsonl"


def check_daemon_status() -> str:
    """Check if the yantra-daemon Docker container or host process is running."""
    # 1. Try Docker CLI (if run on host)
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", "yantra-daemon"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            status = result.stdout.strip().upper()
            return f"UP ({status})"
    except Exception:
        pass
        
    # 2. Try procfs scan (if run inside container or host without Docker CLI)
    try:
        for pid in os.listdir('/proc'):
            if pid.isdigit():
                try:
                    with open(f"/proc/{pid}/cmdline", "r") as f:
                        cmd = f.read().replace('\x00', ' ')
                        if "core.daemon" in cmd and "cli_status" not in cmd:
                            return "UP (PROCESS RUNNING)"
                except Exception:
                    continue
    except Exception:
        pass
            
    return "DOWN"


def main() -> None:
    print("=" * 70)
    print(" Y A N T R A   O S   —   H E A D L E S S   M V P")
    print("=" * 70)
    
    daemon_status = check_daemon_status()
    print(f"\n[DAEMON STATUS]: {daemon_status}")

    total_actions = 0
    records = []

    if os.path.exists(AUDIT_LOG_PATH):
        try:
            with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
                total_actions = len(lines)
                # Parse the last 10 lines
                for line in lines[-10:]:
                    if not line.strip():
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            print(f"[ERROR]: Failed to read audit log: {e}")
    else:
        print(f"\n[INFO]: Audit log not found at {AUDIT_LOG_PATH}. (No actions taken yet)")

    print(f"[TOTAL AUTONOMOUS ACTIONS]: {total_actions}\n")
    
    if records:
        print("-" * 70)
        print(f"{'TIMESTAMP':<24} | {'SHA-256':<8} | {'IMAGE':<20} | {'EXIT'}")
        print("-" * 70)
        
        for rec in records:
            ts = rec.get("timestamp", "UNKNOWN")[:23]  # Truncate microseconds
            sha = rec.get("script_sha256", "UNKNOWN")[:8]
            image = rec.get("image_used", "UNKNOWN")[:20]
            exit_code = rec.get("exit_code", "N/A")
            
            print(f"{ts:<24} | {sha:<8} | {image:<20} | {exit_code}")
            
        print("-" * 70)
    else:
        print("[RECENT ACTIVITY]: None")

    print("\nEnd of Status Report.")


if __name__ == "__main__":
    main()
