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

import logging
import sys

log = logging.getLogger("yantra.daemon")


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
