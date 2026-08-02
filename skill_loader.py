# Copyright (c) 2026 Euryale Ferox Private Limited
# SPDX-License-Identifier: MIT

"""Validate and dispatch data-only skills through the sandbox broker."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from .action_confirmation import confirm_action, log_execution_outcome
    from .sandbox_client import ExecOutcome, MAX_SCRIPT_BYTES, SandboxResult, sandbox
    from .skill_revocation import ensure_skill_allowed
except ImportError:
    from action_confirmation import confirm_action, log_execution_outcome
    from sandbox_client import ExecOutcome, MAX_SCRIPT_BYTES, SandboxResult, sandbox
    from skill_revocation import ensure_skill_allowed


_SKILLS_ROOT = Path(__file__).with_name("skills")
_SKILL_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_SCHEMA = "yantraos/runtime-skill/v1"
_MANIFEST_FIELDS = frozenset({"schema", "id", "version", "actions"})
_ACTION_FIELDS = frozenset({"parameters", "script"})
_PARAMETER_TYPES = frozenset({"boolean", "integer", "number", "string"})
_MAX_MANIFEST_BYTES = 131_072
_MAX_PARAMETERS = 32
_MAX_STRING_BYTES = 8_192
_MAX_INTEGER = (2**53) - 1


@dataclass(frozen=True)
class SkillAction:
    name: str
    parameters: tuple[tuple[str, str], ...]
    script: str


@dataclass(frozen=True)
class Skill:
    id: str
    version: str
    actions: tuple[SkillAction, ...]


@dataclass(frozen=True)
class RegisteredAction:
    skill: Skill
    action: SkillAction


def _read_manifest(manifest_path: Path) -> Any:
    descriptor = -1
    try:
        descriptor = os.open(
            manifest_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_MANIFEST_BYTES:
            raise ValueError
        raw = os.read(descriptor, _MAX_MANIFEST_BYTES + 1)
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise ValueError
        return json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Invalid skill manifest: {manifest_path.name}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _load_skill(manifest_path: Path) -> Skill:
    manifest = _read_manifest(manifest_path)
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_FIELDS:
        raise ValueError(f"Invalid skill manifest fields: {manifest_path.name}")
    skill_id = manifest["id"]
    actions = manifest["actions"]
    if (
        manifest["schema"] != _SCHEMA
        or not isinstance(skill_id, str)
        or not _SKILL_ID.fullmatch(skill_id)
        or not isinstance(manifest["version"], str)
        or not _VERSION.fullmatch(manifest["version"])
        or not isinstance(actions, dict)
        or not actions
        or len(actions) > 64
    ):
        raise ValueError(f"Invalid skill manifest values: {manifest_path.name}")

    parsed_actions: list[SkillAction] = []
    for name, definition in actions.items():
        if (
            not isinstance(name, str)
            or not _SKILL_ID.fullmatch(name)
            or not isinstance(definition, dict)
            or set(definition) != _ACTION_FIELDS
        ):
            raise ValueError(f"Invalid skill action: {skill_id}")
        parameters = definition["parameters"]
        script = definition["script"]
        if (
            not isinstance(parameters, dict)
            or len(parameters) > _MAX_PARAMETERS
            or any(
                not isinstance(parameter, str)
                or not _SKILL_ID.fullmatch(parameter)
                or parameter == "action"
                or parameter_type not in _PARAMETER_TYPES
                for parameter, parameter_type in parameters.items()
            )
            or not isinstance(script, str)
            or not script.strip()
            or "\x00" in script
            or len(script.encode("utf-8")) > MAX_SCRIPT_BYTES
        ):
            raise ValueError(f"Invalid skill action definition: {skill_id}.{name}")
        parsed_actions.append(
            SkillAction(name, tuple(sorted(parameters.items())), script)
        )
    return Skill(skill_id, manifest["version"], tuple(parsed_actions))


@lru_cache(maxsize=1)
def default_skills() -> dict[str, RegisteredAction]:
    """Return the installed first-party skills keyed by action."""
    skills: dict[str, RegisteredAction] = {}
    for manifest_path in sorted(_SKILLS_ROOT.glob("*/skill.json")):
        skill = _load_skill(manifest_path)
        for action in skill.actions:
            if action.name in skills:
                raise ValueError(f"Duplicate skill action: {action.name}")
            skills[action.name] = RegisteredAction(skill, action)
    return skills


def _valid_parameter(value: Any, parameter_type: str) -> bool:
    if parameter_type == "boolean":
        return type(value) is bool
    if parameter_type == "integer":
        return type(value) is int and abs(value) <= _MAX_INTEGER
    if parameter_type == "number":
        return (
            type(value) in {int, float}
            and abs(value) <= _MAX_INTEGER
            and math.isfinite(value)
        )
    return isinstance(value, str) and len(value.encode("utf-8")) <= _MAX_STRING_BYTES


def validate_intent(intent: Any) -> RegisteredAction:
    if not isinstance(intent, dict) or not isinstance(intent.get("action"), str):
        raise ValueError("Intent must contain a skill action.")
    registered = default_skills().get(intent["action"])
    if registered is None:
        raise ValueError(f"Unknown or missing action: {intent['action']!r}.")
    parameters = dict(registered.action.parameters)
    if set(intent) != {"action", *parameters} or any(
        not _valid_parameter(intent[name], parameter_type)
        for name, parameter_type in parameters.items()
    ):
        raise ValueError(f"Intent fields do not match the '{intent['action']}' schema.")
    return registered


def is_skill_intent(intent: Any) -> bool:
    return (
        isinstance(intent, dict)
        and isinstance(intent.get("action"), str)
        and intent["action"] in default_skills()
    )


def _sandbox_script(intent: dict[str, Any], registered: RegisteredAction) -> str:
    encoded = base64.b64encode(
        json.dumps(intent, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).decode("ascii")
    script = (
        f"export YANTRA_SKILL_ID='{registered.skill.id}'\n"
        f"export YANTRA_SKILL_VERSION='{registered.skill.version}'\n"
        f"export YANTRA_SKILL_ACTION='{registered.action.name}'\n"
        f"export YANTRA_SKILL_INPUT_B64='{encoded}'\n"
        f"{registered.action.script}"
    )
    if len(script.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise ValueError("Compiled skill script exceeds the sandbox limit.")
    return script


def execute_intent(intent: dict[str, Any]) -> SandboxResult:
    """Confirm and execute one typed skill action through the root broker."""
    registered = validate_intent(intent)
    ensure_skill_allowed(registered.skill.id, registered.skill.version)
    if not confirm_action(intent):
        raise PermissionError("Skill action was not approved.")

    # Re-read after the prompt so a newly promoted revocation cannot use stale approval.
    ensure_skill_allowed(registered.skill.id, registered.skill.version)
    result = asyncio.run(sandbox.execute(_sandbox_script(intent, registered)))
    success = result.outcome == ExecOutcome.SUCCESS and result.exit_code == 0
    if not log_execution_outcome(
        intent,
        success=success,
        result_msg=f"Sandbox exit {result.exit_code}.",
        error_msg=result.error or result.stderr or result.outcome.value,
    ):
        return SandboxResult(
            outcome=ExecOutcome.DOCKER_ERROR,
            script_hash=result.script_hash,
            error="Skill outcome audit failed.",
        )
    return result
