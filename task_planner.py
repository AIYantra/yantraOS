# Copyright (c) 2026 Euryale Ferox Private Limited
# SPDX-License-Identifier: MIT

"""Bounded Terra planning for terminal-originated YantraOS tasks."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
from typing import Any

try:
    from .computer_use_bridge import select_task_route, validate_task_intent
    from .foundry_action_bridge import validate_intent as validate_browser_intent
    from .hybrid_router import complete, tier_for_complexity
    from .trusted_guidance import load_guidance
except ImportError:
    from computer_use_bridge import select_task_route, validate_task_intent
    from foundry_action_bridge import validate_intent as validate_browser_intent
    from hybrid_router import complete, tier_for_complexity
    from trusted_guidance import load_guidance


log = logging.getLogger("yantra.task_planner")

MAX_QUERY_BYTES = 8_192
MAX_PLAN_STEPS = 5
_PLANNER_FIELDS = frozenset({"action", "complexity", "route", "model_tier"})
_COMPLEXITIES = frozenset({"low", "medium", "high"})
_MODEL_TIERS = frozenset({"luna", "terra", "sol"})
_ROUTES = frozenset({"CLI_FAST_PATH", "COMPUTER_USE", "PLAYWRIGHT", "REJECTED"})
_SEARCH_RE = re.compile(
    r"^\s*(?:open|launch|start)\s+(?:the\s+)?(?P<app>[A-Za-z0-9 ._-]+?)"
    r"(?:\s+(?:app|application))?\s+and\s+search(?:\s+for)?\s+"
    r"(?P<query>.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_TELEGRAM_USERNAME_RE = re.compile(r"@(?P<username>[A-Za-z0-9_]{5,32})")
_PERSONAL_FOLDER_RE = re.compile(
    r"\b(?:my|the)\s+(?:music|desktop|downloads|pictures|videos)\s+folder\b",
    re.IGNORECASE,
)
_ABSOLUTE_OUTPUT_RE = re.compile(
    r"\b(?:into|save(?:\s+(?:it|the\s+\w+))?\s+(?:as\s+)?|write\s+to)\s+"
    r"(?P<path>(?:~|/)[^\s\"']+)",
    re.IGNORECASE,
)

_PLANNER_PROMPT = """You are the YantraOS task planner. Return ONLY one JSON object:
{"steps":[{"action":{...},"complexity":"low|medium|high","route":"CLI_FAST_PATH|COMPUTER_USE|REJECTED","model_tier":"luna|terra|sol"}]}

Plan at most five ordered, atomic steps. `route` and `model_tier` are advisory:
the host independently validates them and may override them.

Supported action payloads:
1. File create/move only inside the managed YantraOS directory:
   {"action":"file_management","operation":"create","path":"visible-relative-path","content":"optional text"}
   {"action":"file_management","operation":"move","path":"visible-relative-path","destination":"visible-relative-path"}
   Always use this for a requested file create or move. Never use computer_use_task for it.
2. Supervised desktop work:
   {"action":"computer_use_task","instruction":"one visible atomic task"}
3. Anonymous public read-only website extraction:
   {"action":"navigate_and_extract","url":"https://public.example/path","instruction":"exact facts to extract","output_path":"extractions/result.txt"}
   Use this only when the user gives an explicit public URL and asks to read or
    extract data. Never use it for login, cookies, forms, clicks, typing,
    uploads, edits, purchases, or authenticated pages; use computer_use_task
    for those visible workflows.
   When public research must become a document, use this action to write the
   document directly. Do not rely on unstructured visual output from one step
   as data for a later file-editing step.

Known app launches must be their own step, for example:
{"action":"computer_use_task","instruction":"Open Firefox"}
For `open firefox and search yantraos`, emit two steps: Open Firefox, then a
browser step that says Firefox is already open and uses Ctrl+L, types the exact
query, presses Enter, and visually verifies the result. Do not use the desktop
launcher when the app is already open. Prefer keyboard shortcuts over clicks.
For a Telegram task targeting `@username`, emit `Open Telegram chat @username`
as one CLI step using Telegram's registered deep link. Do not emit separate
Telegram launch or chat-search steps. Follow it with a visual step that types,
verifies the recipient, and sends the requested message.

Use low complexity for routine keyboard/browser navigation, medium for
multi-screen or ambiguous workflows, and high only for genuinely difficult
work. Map low to luna, medium to terra, and high to sol. Deterministic file
and app-launch steps still need a complexity/model_tier value, but the host
will execute them without a model."""


class TaskPlanError(ValueError):
    """The planner returned no safe, executable task plan."""


def _strip_fences(value: str) -> str:
    value = value.strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    return value.strip()


def _parse_response(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(_strip_fences(value))
    except json.JSONDecodeError as exc:
        raise TaskPlanError("Terra planner returned invalid JSON.") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"steps"}:
        raise TaskPlanError("Terra planner must return only a steps object.")
    steps = parsed["steps"]
    if not isinstance(steps, list) or not steps or len(steps) > MAX_PLAN_STEPS:
        raise TaskPlanError("Terra planner returned an invalid number of steps.")
    return steps


def _file_action(query: str) -> dict[str, Any] | None:
    try:
        tokens = shlex.split(query.rstrip())
    except ValueError:
        return None
    if not tokens:
        return None

    words = [token.casefold() for token in tokens]
    if words[0] == "create":
        index = 1
        while index < len(words) and words[index] in {
            "a", "the", "new", "text", "markdown", "md", "json", "python",
        }:
            index += 1
        if index >= len(words) or words[index] != "file":
            return None
        index += 1
        if index < len(words) and words[index] in {"called", "named"}:
            index += 1
        if index >= len(tokens):
            return None
        path = tokens[index].rstrip(".")
        remainder = tokens[index + 1:]
        lowered = [token.casefold() for token in remainder]
        if lowered[:2] == ["with", "content"]:
            remainder = remainder[2:]
        elif lowered[:1] == ["containing"]:
            remainder = remainder[1:]
        elif remainder:
            return None
        return {
            "action": "file_management",
            "operation": "create",
            "path": path,
            "content": " ".join(remainder),
        }

    if words[0] == "move":
        index = 1
        while index < len(words) and words[index] in {"a", "the"}:
            index += 1
        if index < len(words) and words[index] == "file":
            index += 1
        if index + 2 >= len(tokens) or words[index + 1] != "to":
            return None
        if index + 3 != len(tokens):
            return None
        return {
            "action": "file_management",
            "operation": "move",
            "path": tokens[index],
            "destination": tokens[index + 2].rstrip("."),
        }
    return None


def _template_actions(query: str) -> list[dict[str, Any]] | None:
    match = _SEARCH_RE.fullmatch(query)
    if match:
        app = match.group("app").strip()
        search_query = match.group("query").strip().rstrip(".")
        launch = {"action": "computer_use_task", "instruction": f"Open {app}"}
        try:
            route, _ = select_task_route(launch)
        except ValueError:
            route = "REJECTED"
        if route == "CLI_FAST_PATH" and search_query:
            return [
                launch,
                {
                    "action": "computer_use_task",
                    "instruction": (
                        f"Wait until {app} is visible and focused. {app} is already "
                        f"open. Use Ctrl+L to focus the address bar, type this exact "
                        f"search query without quotation marks: {search_query}, press "
                        "Enter, and visually verify the results."
                    ),
                },
            ]

    file_action = _file_action(query)
    if file_action is not None:
        return [file_action]

    launch = {"action": "computer_use_task", "instruction": query.strip()}
    try:
        route, _ = select_task_route(launch)
    except ValueError:
        route = "REJECTED"
    return [launch] if route == "CLI_FAST_PATH" else None


def _telegram_username(query: str) -> str | None:
    if "telegram" not in query.casefold():
        return None
    match = _TELEGRAM_USERNAME_RE.search(query)
    return match.group("username") if match else None


def _is_telegram_navigation_step(step: Any) -> bool:
    if not isinstance(step, dict):
        return False
    action = step.get("action")
    if not isinstance(action, dict) or action.get("action") != "computer_use_task":
        return False
    instruction = str(action.get("instruction", "")).casefold()
    if "telegram" not in instruction:
        return False
    if any(word in instruction for word in ("type", "write", "message", "send")):
        return False
    return any(word in instruction for word in ("open", "launch", "search", "find"))


def _telegram_template_steps(
    query: str, raw_steps: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    username = _telegram_username(query)
    if username is None:
        return None
    remaining = [step for step in raw_steps if not _is_telegram_navigation_step(step)]
    if len(remaining) == len(raw_steps):
        return None
    launch = {
        "action": "computer_use_task",
        "instruction": f"Open Telegram chat @{username}",
    }
    continuations: list[dict[str, Any]] = []
    for step in remaining:
        if not isinstance(step, dict):
            continuations.append(step)
            continue
        action = step.get("action")
        if not isinstance(action, dict) or action.get("action") != "computer_use_task":
            continuations.append(step)
            continue
        continuation = dict(step)
        continuation_action = dict(action)
        continuation_action["instruction"] = (
            f"Telegram chat @{username} is already open via a verified deep link. "
            "Never open Telegram, use the app launcher, or search for a chat. "
            "Verify the visible username before typing or sending. "
            + str(action.get("instruction", ""))
        )
        continuation["action"] = continuation_action
        continuations.append(continuation)
    return [_host_step(launch, "low"), *_validated_steps(continuations)]


def _complexity(value: Any) -> str:
    if not isinstance(value, str) or value.casefold() not in _COMPLEXITIES:
        raise TaskPlanError("Each Terra step needs low, medium, or high complexity.")
    return value.casefold()


def _host_step(action: Any, complexity: str) -> dict[str, Any]:
    if isinstance(action, dict) and action.get("action") == "navigate_and_extract":
        try:
            validate_browser_intent(action)
        except (OSError, ValueError) as exc:
            raise TaskPlanError(
                f"Terra planner proposed an invalid browser extraction: {exc}"
            ) from exc
        return {
            "action": action,
            "complexity": complexity,
            "route": "PLAYWRIGHT",
            "route_reason": "public anonymous data extraction uses Playwright",
            "model_tier": None,
        }
    try:
        typed_action = validate_task_intent(action)
        route, route_reason = select_task_route(typed_action)
    except ValueError as exc:
        raise TaskPlanError(f"Terra planner proposed an invalid action: {exc}") from exc
    if route == "REJECTED":
        raise TaskPlanError(f"Terra planner proposed a rejected action: {route_reason}")
    return {
        "action": typed_action,
        "complexity": complexity,
        "route": route,
        "route_reason": route_reason,
        "model_tier": tier_for_complexity(complexity) if route == "COMPUTER_USE" else None,
    }


def _validated_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict) or set(step) != _PLANNER_FIELDS:
            raise TaskPlanError("Terra planner step does not match the required schema.")
        complexity = _complexity(step.get("complexity"))
        route = step.get("route")
        model_tier = step.get("model_tier")
        if not isinstance(route, str) or route.upper() not in _ROUTES or not isinstance(model_tier, str):
            raise TaskPlanError("Terra planner step has invalid route metadata.")
        if model_tier.casefold() not in _MODEL_TIERS:
            raise TaskPlanError("Terra planner step has an invalid model tier.")
        validated.append(_host_step(step.get("action"), complexity))
    return validated


def _template_steps(
    template: list[dict[str, Any]], raw_steps: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    complexities = ["low"] * len(template)
    if raw_steps is not None:
        for index, step in enumerate(raw_steps[:len(template)]):
            if isinstance(step, dict):
                try:
                    complexities[index] = _complexity(step.get("complexity"))
                except TaskPlanError:
                    pass
    return [_host_step(action, complexities[index]) for index, action in enumerate(template)]


def _normalize_browser_continuations(
    steps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Prevent a visual browser step from launching an app already opened by CLI."""
    browser_open = False
    normalized: list[dict[str, Any]] = []
    for step in steps:
        action = step["action"]
        instruction = str(action.get("instruction", ""))
        instruction_lower = instruction.casefold()
        if (
            step["route"] == "CLI_FAST_PATH"
            and action.get("action") == "computer_use_task"
            and any(name in instruction_lower for name in ("firefox", "browser"))
        ):
            browser_open = True
            normalized.append(step)
            continue
        if (
            browser_open
            and step["route"] == "COMPUTER_USE"
            and action.get("action") == "computer_use_task"
            and any(name in instruction_lower for name in ("firefox", "browser", "hacker news"))
        ):
            continuation = dict(action)
            continuation["instruction"] = (
                "Firefox is already open via the prior CLI step. Never launch Firefox "
                "or use the desktop launcher. "
                + instruction
            )
            normalized.append(_host_step(continuation, step["complexity"]))
            continue
        normalized.append(step)
    return normalized


def plan_query(query: str) -> list[dict[str, Any]]:
    """Ask Terra to plan a prompt, then replace advisory routing with host policy."""
    if not isinstance(query, str) or not query.strip():
        raise TaskPlanError("Task query must be a non-empty string.")
    if len(query.encode("utf-8")) > MAX_QUERY_BYTES or "\x00" in query:
        raise TaskPlanError("Task query is unsafe or too large.")
    if _PERSONAL_FOLDER_RE.search(query):
        raise TaskPlanError(
            "Managed file actions are confined to ~/Documents/YantraOS; "
            "personal folders such as Music are not supported."
        )
    absolute_output = _ABSOLUTE_OUTPUT_RE.search(query)
    if absolute_output:
        raise TaskPlanError(
            "Output paths must be relative to ~/Documents/YantraOS/Foundry, "
            "for example extractions/result.txt; "
            f"{absolute_output.group('path')} is not supported."
        )

    messages = [
        {
            "role": "system",
            "content": _PLANNER_PROMPT
            + "\n\nBuilt-in browser reference:\n"
            + load_guidance("browser"),
        },
        {"role": "user", "content": query.strip()},
    ]
    try:
        response = asyncio.run(complete(messages, cognitive_tier="TERRA"))
    except Exception as exc:
        raise TaskPlanError(f"Terra planner failed: {exc}") from exc
    if not isinstance(response, str):
        raise TaskPlanError("Terra planner returned no text plan.")

    template = _template_actions(query)
    try:
        raw_steps = _parse_response(response)
    except TaskPlanError:
        if template is None:
            raise
        log.warning("Terra plan was malformed; using the bounded host template.")
        raw_steps = None

    telegram_steps = _telegram_template_steps(query, raw_steps) if raw_steps is not None else None
    if telegram_steps is not None:
        steps = telegram_steps
    elif template is not None:
        steps = _template_steps(template, raw_steps)
    else:
        steps = _validated_steps(raw_steps)
    steps = _normalize_browser_continuations(steps)
    log.info("Terra planned %d step(s); host validated every route.", len(steps))
    return steps
