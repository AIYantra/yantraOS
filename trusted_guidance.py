# Copyright (c) 2026 Euryale Ferox Private Limited
# SPDX-License-Identifier: MIT

"""Fixed, release-controlled Markdown guidance for YantraOS prompts."""

from __future__ import annotations

import logging
import os
import stat
import unicodedata
from functools import lru_cache
from pathlib import Path


log = logging.getLogger("yantra.trusted_guidance")

_MAX_GUIDANCE_BYTES = 4_096
_GUIDANCE_FILES = {
    "browser": Path(__file__).with_name("skills") / "browser" / "SKILL.md",
    "linux_sandbox": (
        Path(__file__).with_name("skills") / "linux-automation" / "SKILL.md"
    ),
}


@lru_cache(maxsize=None)
def load_guidance(name: str) -> str:
    """Load one fixed, non-writable Markdown reference or return no guidance."""
    path = _GUIDANCE_FILES.get(name)
    if path is None:
        return ""
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        log.warning("Trusted guidance %s is unavailable: %s", name, exc)
        return ""
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid not in {0, os.geteuid()}
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            log.warning("Trusted guidance %s has unsafe metadata.", name)
            return ""
        raw = os.read(descriptor, _MAX_GUIDANCE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > _MAX_GUIDANCE_BYTES:
        log.warning("Trusted guidance %s exceeds its size limit.", name)
        return ""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        log.warning("Trusted guidance %s is not valid UTF-8.", name)
        return ""
    if any(
        character not in "\n\t"
        and unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        for character in text
    ):
        log.warning("Trusted guidance %s contains hidden control characters.", name)
        return ""
    return text
