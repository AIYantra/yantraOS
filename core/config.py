"""
YantraOS — Configuration Loader
Target: /opt/yantra/core/config.py

Lightweight parser that reads config.yaml from the project root
(/opt/yantra/config.yaml in production, or ../config.yaml relative to this file).

Exports get_settings() which returns the parsed YAML dictionary.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

_settings_cache: Dict[str, Any] | None = None


def _locate_config() -> Path:
    """
    Resolve config.yaml location.
    Search order:
      1. $YANTRA_CONFIG env var (explicit override)
      2. /opt/yantra/config.yaml (production path)
      3. ../config.yaml relative to this file (development fallback)
    """
    env_path = os.environ.get("YANTRA_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p

    # Production path
    prod = Path("/opt/yantra/config.yaml")
    if prod.is_file():
        return prod

    # Development fallback: core/ -> parent dir
    dev = Path(__file__).resolve().parent.parent / "config.yaml"
    if dev.is_file():
        return dev

    raise FileNotFoundError(
        "config.yaml not found. Searched: "
        f"$YANTRA_CONFIG={env_path}, /opt/yantra/config.yaml, {dev}"
    )


def get_settings() -> Dict[str, Any]:
    """
    Parse and return the config.yaml as a dictionary.
    Results are cached after the first call.

    Falls back to an empty dict if PyYAML is not installed or the
    config file is missing — the daemon should degrade gracefully,
    not crash on a missing config.
    """
    global _settings_cache

    if _settings_cache is not None:
        return _settings_cache

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "CONFIG: PyYAML not installed — returning empty settings. "
            "Install with: pip install pyyaml"
        )
        _settings_cache = {}
        return _settings_cache

    try:
        config_path = _locate_config()
        with open(config_path, "r") as f:
            _settings_cache = yaml.safe_load(f) or {}
        logger.info(f"CONFIG: Loaded settings from {config_path}")
    except FileNotFoundError as e:
        logger.warning(f"CONFIG: {e} — using empty defaults.")
        _settings_cache = {}
    except Exception as e:
        logger.warning(f"CONFIG: Failed to parse config.yaml: {e} — using empty defaults.")
        _settings_cache = {}

    return _settings_cache or {}
