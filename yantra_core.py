# Copyright (c) 2026 Euryale Ferox Private Limited
# SPDX-License-Identifier: MIT

import os
import sys
import json
import subprocess
import logging
from typing import List, Dict, Any

try:
    from .computer_use_bridge import (
        run_intent_result as run_external_action_result,
        select_task_route,
    )
    from .task_planner import TaskPlanError, plan_query
    from .skill_loader import execute_intent as execute_skill_intent, is_skill_intent
except ImportError:
    from computer_use_bridge import (
        run_intent_result as run_external_action_result,
        select_task_route,
    )
    from task_planner import TaskPlanError, plan_query
    from skill_loader import execute_intent as execute_skill_intent, is_skill_intent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)

log = logging.getLogger("yantra.core")

def execute_actions(
    actions: List[Dict[str, Any]], *, approve_steps: bool = False,
    model_tier: str | None = None,
    task_approved: bool = False,
) -> bool:
    # Import the confirmation gate (M2: first 20 runs require human approval)
    try:
        from .action_confirmation import confirm_action, log_execution_outcome
    except ImportError:
        from action_confirmation import confirm_action, log_execution_outcome

    for idx, action_intent in enumerate(actions):
        action_label = action_intent.get('action', 'unknown')
        log.info(f"Proposed action {idx+1}/{len(actions)}: {action_label}")

        if action_label in {"file_management", "computer_use_task"}:
            try:
                route, route_reason = select_task_route(action_intent)
                log.info(
                    "REASON ROUTE: %s selected because %s.",
                    route,
                    route_reason,
                )
                dispatch_kwargs: dict[str, Any] = {}
                if approve_steps:
                    dispatch_kwargs["approve_steps"] = True
                if route == "COMPUTER_USE" and model_tier is not None:
                    dispatch_kwargs["model_tier"] = model_tier
                if task_approved:
                    dispatch_kwargs["task_approved"] = True
                result = run_external_action_result(action_intent, **dispatch_kwargs)
                succeeded = result.exit_code == 0
            except (OSError, RuntimeError, ValueError) as exc:
                log.error("Unprivileged external action failed: %s", exc)
                succeeded = False
                result = None
            if not succeeded:
                if result is not None:
                    log.error("TASK FAILED: %s", result.reason)
                log.error("Stopping remaining actions because a prerequisite failed.")
                return False
            continue

        try:
            skill_action = is_skill_intent(action_intent)
        except ValueError as exc:
            log.error("Skill registry validation failed: %s", exc)
            return False
        if skill_action:
            try:
                result = execute_skill_intent(action_intent)
            except (OSError, PermissionError, RuntimeError, ValueError) as exc:
                log.error("Sandboxed skill failed closed: %s", exc)
                return False
            if result.exit_code != 0:
                log.error("Sandboxed skill failed: %s", result.error or result.stderr)
                return False
            continue

        # ── Confirmation gate (audit-logs the proposal automatically) ─
        confirmation_kwargs: dict[str, Any] = {}
        if task_approved:
            confirmation_kwargs = {
                "preapproved": True,
                "approval_context": "plan_level_approval",
            }
        if not confirm_action(action_intent, **confirmation_kwargs):
            log.info(f"Action {idx+1}/{len(actions)} SKIPPED (rejected or no TTY).")
            return False

        # ── Execute the action ────────────────────────────────────────
        intent_str = json.dumps(action_intent)
        log.info(f"Executing action {idx+1}/{len(actions)}: {action_label}")
        
        bridge_path = os.path.join(os.path.dirname(__file__), "foundry_action_bridge.py")

        try:
            result = subprocess.run(
                [sys.executable, bridge_path, "--approved"],
                input=intent_str,
                text=True,
                capture_output=True,
            )
            if result.returncode == 0:
                log.info("Action succeeded (model declared done).")
                if not log_execution_outcome(
                    action_intent,
                    success=True,
                    result_msg="Bridge exit 0 (task completed).",
                ):
                    log.error("Action succeeded but its outcome audit was not persisted.")
                    return False
            else:
                error_message = (result.stderr or result.stdout or "").strip()
                if not error_message:
                    error_message = f"Bridge exit {result.returncode}."
                log.error("TASK FAILED: %s", error_message)
                if not log_execution_outcome(
                    action_intent,
                    success=False,
                    error_msg=error_message,
                ):
                    log.error("Action failed but its outcome audit was not persisted.")
                return False
        except Exception as e:
            log.error("TASK FAILED: Failed to launch bridge subprocess: %s", e)
            if not log_execution_outcome(
                action_intent,
                success=False,
                error_msg=f"Subprocess launch error: {e}",
            ):
                log.error("Subprocess failure audit was not persisted.")
            return False
    return True


def _confirm_task_plan(planned_steps: list[dict[str, Any]]) -> bool:
    try:
        from .action_confirmation import confirm_action
    except ImportError:
        from action_confirmation import confirm_action

    lines = ["Reviewed task plan:"]
    for index, step in enumerate(planned_steps, start=1):
        action = step["action"]
        if action["action"] == "file_management":
            if action["operation"] == "move":
                detail = f"Move {action['path']} to {action['destination']}"
            else:
                detail = f"Create {action['path']}"
        elif action["action"] == "navigate_and_extract":
            detail = (
                f"Extract {action['url']} to {action['output_path']}: "
                f"{action['instruction'][:160]}"
            )
        else:
            detail = action.get("instruction", action["action"])[:320]
        lines.append(
            f"{index}. {detail} [{step['route']}; "
            f"model={step['model_tier'] or 'none'}]"
        )
    return confirm_action({"action": "task_plan", "instruction": "\n".join(lines)})


def process_query(query: str, *, approve_steps: bool = False) -> bool:
    log.info(f"Processing query: {query}")
    try:
        planned_steps = plan_query(query)
    except TaskPlanError as exc:
        log.error("Terra task planner rejected the request: %s", exc)
        return False

    if not _confirm_task_plan(planned_steps):
        log.warning("Task plan rejected before any action was executed.")
        return False

    for index, step in enumerate(planned_steps, start=1):
        log.info(
            "TASK PLAN %d/%d: route=%s model=%s complexity=%s.",
            index,
            len(planned_steps),
            step["route"],
            step["model_tier"] or "none",
            step["complexity"],
        )
        if not execute_actions(
            [step["action"]],
            approve_steps=approve_steps,
            model_tier=step["model_tier"],
            task_approved=True,
        ):
            return False
    return True


def _parse_cli_arguments(arguments: list[str]) -> tuple[list[str], bool]:
    approve_steps = "--approve-steps" in arguments
    query_arguments = [
        argument
        for argument in arguments
        if argument not in {"--approve-steps", "--confirm-steps"}
    ]
    return query_arguments, approve_steps

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    os.environ.setdefault(
        "YANTRA_AUDIT_LOG_PATH",
        os.path.join(
            os.path.expanduser("~"),
            ".local",
            "state",
            "yantra",
            "audit.jsonl",
        ),
    )
    
    arguments = sys.argv[1:]
    arguments, approve_steps = _parse_cli_arguments(arguments)
    if not arguments:
        print("Usage: python yantra_core.py [--approve-steps] <natural language query>")
        sys.exit(1)

    query = " ".join(arguments)
    raise SystemExit(0 if process_query(query, approve_steps=approve_steps) else 1)
