"""
YantraOS — Daemon Entry Point
Target: /opt/yantra/core/daemon.py
Milestone 5

Production entry point for the Kriya Loop daemon, invoked by systemd:
  ExecStart=/opt/yantra/venv/bin/python3 /opt/yantra/core/daemon.py

This module exists as a thin launcher that:
  1. Configures structured logging to stdout (captured by journal via
     StandardOutput=journal in yantra.service).
  2. Calls engine.main() to start the Kriya Loop.
  3. Catches and logs any fatal exceptions that escape the engine.

This is NOT the same as __main__.py (which supports `python -m core`).
This file is the explicit systemd ExecStart target, ensuring the daemon
is always launched from a predictable, absolute path.
"""

from __future__ import annotations

import json
import logging
import os
import sys

log = logging.getLogger("yantra.daemon")


def heal_litellm_matrix():
    """Autonomous pre-flight check with dynamic path resolution and strict exception shielding."""
    # Anchor to the venv site-packages, not any arbitrary site-packages on sys.path
    site_packages = next(
        (p for p in sys.path if 'site-packages' in p and '/opt/yantra/venv/' in p),
        None
    )
    if site_packages is None:
        # Ultimate fallback: derive from sys.prefix (set by venv activation)
        site_packages = os.path.join(
            sys.prefix, 'lib',
            f'python{sys.version_info.major}.{sys.version_info.minor}',
            'site-packages'
        )

    base_path = os.path.join(site_packages, "litellm")

    files_to_mock = [
        "model_prices_and_context_window_backup.json",
        "litellm_core_utils/tokenizers/anthropic_tokenizer.json",
        "contains/endpoints.json",
        "llms/tokenizers/anthropic_tokenizer.json"
    ]

    healed = 0
    failed = 0
    for file_path in files_to_mock:
        full_path = os.path.join(base_path, file_path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            if not os.path.exists(full_path):
                with open(full_path, 'w') as f:
                    json.dump({}, f)
                healed += 1
        except Exception as e:
            failed += 1
            print(f"Matrix heal FAILED for {file_path}: {e}", flush=True)

    if failed > 0:
        print(
            f"CRITICAL: {failed}/{len(files_to_mock)} litellm cache files could not be "
            f"reconstructed. Daemon crash imminent.", flush=True
        )
    elif healed > 0:
        print(f"Matrix healed: {healed} file(s) reconstructed at {base_path}", flush=True)


# Execute the healing sequence before importing the router
heal_litellm_matrix()

# Diagnostic check for cloud routing fallback credentials
if "GEMINI_API_KEY" not in os.environ:
    print("WARNING: GEMINI_API_KEY missing. Cloud routing will fail if no local GPU is found.", flush=True)


def main() -> None:
    """
    Configure logging and launch the Kriya Loop engine.

    Exit codes:
      0 — Graceful shutdown (SIGTERM or SIGINT)
      1 — Fatal error during startup or Kriya Loop
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )

    log.info("> DAEMON: YantraOS daemon starting...")

    try:
        from core.engine import KriyaLoopEngine
        import asyncio

        engine = KriyaLoopEngine()
        asyncio.run(engine.run())

    except KeyboardInterrupt:
        log.info("> DAEMON: Interrupted (SIGINT). Exiting.")
        sys.exit(0)

    except Exception as exc:
        log.critical(f"> DAEMON: Fatal error: {exc}", exc_info=True)
        sys.exit(1)

    log.info("> DAEMON: Clean exit.")
    sys.exit(0)


if __name__ == "__main__":
    main()
