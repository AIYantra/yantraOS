# Copyright (c) 2026 Euryale Ferox Private Limited
# SPDX-License-Identifier: MIT

"""Small, evidence-producing adapter for the YantraOS evaluation runner."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any


class YantraEvalAgent:
    """Request exactly one bounded shell action from one explicit router tier."""

    _TIERS = {"luna": "SENSE", "terra": "TERRA", "sol": "SOL"}

    def __init__(self, tier: str) -> None:
        if tier not in self._TIERS:
            raise ValueError(f"Unknown evaluation tier: {tier}")
        from core.hybrid_router import get_router

        self.router = get_router()
        self.tier = tier
        self.steps: list[dict[str, Any]] = []

    def predict(self, instruction: str, observation: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": (
                    "Return exactly one JSON object. Allowed actions are "
                    '{"action":"execute_bash","command":"..."} or '
                    '{"action":"done","reason":"..."}. Execute only the requested '
                    "task in the supplied working directory."
                ),
            },
            {
                "role": "user",
                "content": f"Task: {instruction}\nObservation: {json.dumps(observation)}",
            },
        ]
        started = time.perf_counter()
        raw = asyncio.run(self.router.complete(
            messages, cognitive_tier=self._TIERS[self.tier], timeout=30.0
        ))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        content = ""
        try:
            content = raw.choices[0].message.content
            text = content.lstrip()
            action, end = json.JSONDecoder().raw_decode(text)
        except (AttributeError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Model did not return one JSON action: {str(content)[:200]!r}") from exc
        if action.get("action") == "execute_bash" and isinstance(action.get("command"), str):
            pass
        elif action.get("action") == "done" and isinstance(action.get("reason", ""), str):
            pass
        else:
            raise RuntimeError("Model returned an unsupported evaluation action.")

        usage = getattr(raw, "usage", None)
        self.steps.append({
            "requested_tier": self.tier,
            "model": self.router.last_model,
            "output_compliant": not text[end:].strip(),
            "latency_ms": elapsed_ms,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        })
        return action

    def metrics(self) -> dict[str, Any]:
        known_prompt = [step["prompt_tokens"] for step in self.steps]
        known_completion = [step["completion_tokens"] for step in self.steps]
        return {
            "steps": self.steps,
            "total_steps": len(self.steps),
            "prompt_tokens": sum(known_prompt) if all(v is not None for v in known_prompt) else None,
            "completion_tokens": sum(known_completion) if all(v is not None for v in known_completion) else None,
        }
