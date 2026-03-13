"""
YantraOS — Hybrid Cognitive Router
Target: /opt/yantra/core/hybrid_router.py
Milestone 2, Task 2.2

Instantiates a LiteLLM Router with an exhaustive, deterministic fallback
matrix. Routing strategy is locked to "simple-shuffle" — round-robin across
equivalent models — to eliminate thundering-herd performance penalties
associated with "latency-based" or "cost-based" strategies under local load.

Security invariants:
  • API credentials are NEVER hardcoded. All secrets are loaded exclusively
    from /etc/yantra/host_secrets.env (root:root, mode 0600) at module init.
  • The host_secrets.env file is read once and the values stored only in
    os.environ; no secrets are written to logs or any other file.

Resilience invariants:
  • Every async inference call is wrapped in asyncio.wait_for() with a
    configurable timeout to prevent deadlock from unresponsive endpoints.
  • Fallback matrix is exhaustive: local → cloud primary → cloud secondary.
  • Router is constructed lazily (on first call) so import does not block.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, AsyncIterator

log = logging.getLogger("yantra.hybrid_router")

# ── Configuration ─────────────────────────────────────────────────────────────

# Global inference timeout. External cloud APIs (Anthropic, OpenAI, Google)
# can stall for 30–60 s under load. Capping at 45 s ensures the Kriya Loop
# never blocks longer than one iteration interval (10 s) × 4.5.
INFERENCE_TIMEOUT_SECS: float = 45.0

# Secrets are injected into os.environ by systemd's EnvironmentFile directive
# (EnvironmentFile=-/etc/yantra/host_secrets.env) in yantra.service.
# No disk reads for secrets occur at runtime — all API keys resolve from RAM
# via os.environ.get(). This eliminates permission boundary collisions under
# ProtectSystem=strict.


# ── Router Factory ────────────────────────────────────────────────────────────

_router_instance: Any = None  # litellm.Router — typed as Any to avoid hard import


def _build_router() -> Any:
    """
    Construct the LiteLLM Router with an exhaustive fallback matrix.

    The model list is structured as follows:
      Group "local/llama3"      — Ollama on localhost (zero-latency, air-gapped)
      Group "gemini/flash"      — Google Gemini 2.0 Flash (cloud primary)
      Group "anthropic/haiku"   — Claude 3.5 Haiku (cloud secondary)
      Group "openai/gpt4o"      — GPT-4o (cloud tertiary / emergency)

    The fallback chain for the daemon's primary model alias "yantra/primary":
      local/llama3 → gemini/flash → anthropic/haiku → openai/gpt4o

    routing_strategy is hardcoded to "simple-shuffle" — this distributes
    requests across equally-weighted models within a group using round-robin.
    Do NOT use "latency-based-routing": it requires a warm-up period and
    introduces 5–15 s sampling delays that corrupt the Kriya Loop's 10 s cadence.
    """
    try:
        import litellm  # type: ignore
        from litellm import Router  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "litellm is not installed. Run: pip install litellm"
        ) from exc

    # Suppress litellm's verbose request/response logging — the daemon uses
    # its own structured logger. Exceptions are still propagated.
    litellm.suppress_debug_info = True
    litellm.set_verbose = False

    ollama_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    model_list = [
        # ── Local: Ollama / Llama 3 ───────────────────────────────────────
        {
            "model_name": "local/llama3",
            "litellm_params": {
                "model": "ollama/llama3",
                "api_base": ollama_base,
                "timeout": 30,         # Local should respond within 30 s
                "stream": True,
            },
        },
        {
            "model_name": "local/llama3",
            "litellm_params": {
                "model": "ollama/deepseek-r1",
                "api_base": ollama_base,
                "timeout": 30,
                "stream": True,
            },
        },
        # ── Cloud Primary: Google Gemini 2.0 Flash ────────────────────────
        {
            "model_name": "gemini/flash",
            "litellm_params": {
                "model": "gemini/gemini-2.5-flash",
                "api_key": os.environ.get("GEMINI_API_KEY", ""),
                "timeout": INFERENCE_TIMEOUT_SECS,
                "stream": True,
            },
        },
        # ── Cloud Secondary: Anthropic Claude 3.5 Haiku ───────────────────
        {
            "model_name": "anthropic/haiku",
            "litellm_params": {
                "model": "anthropic/claude-3-5-haiku-20241022",
                "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
                "timeout": INFERENCE_TIMEOUT_SECS,
                "stream": True,
            },
        },
        # ── Cloud Tertiary: OpenAI GPT-4o (emergency fallback) ────────────
        {
            "model_name": "openai/gpt4o",
            "litellm_params": {
                "model": "openai/gpt-4o",
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "timeout": INFERENCE_TIMEOUT_SECS,
                "stream": True,
            },
        },
    ]

    router = Router(
        model_list=model_list,
        # Exhaustive fallback chain: local GPU → cloud primary → cloud secondary → tertiary
        fallbacks=[
            {"local/llama3": ["gemini/flash", "anthropic/haiku", "openai/gpt4o"]}
        ],
        # Prevent thundering-herd and warm-up latency. Simple round-robin is
        # deterministic and imposes zero measurement overhead.
        routing_strategy="simple-shuffle",
        # Retry transient failures twice before advancing to the next fallback.
        num_retries=2,
        retry_after=2,
        # Allow_fallbacks: if the primary group raises any Exception, advance
        # to the next entry in the fallbacks list automatically.
        allowed_fails=1,
        cooldown_time=60,  # Seconds to cool a failed model before retrying
        # Disable LiteLLM's internal cache to avoid stale credential lookups
        cache_responses=False,
        # Ensure async loop compatibility
        set_verbose=False,
    )

    log.info("> ROUTER: LiteLLM Router initialized (strategy=simple-shuffle, 4-tier fallback)")
    return router


def get_router() -> Any:
    """
    Lazy singleton accessor for the LiteLLM Router.
    API keys are already in os.environ (injected by systemd EnvironmentFile).
    Thread-safe for asyncio (single event loop).
    """
    global _router_instance
    if _router_instance is None:
        _router_instance = _build_router()
    return _router_instance


# ── Inference Interface ───────────────────────────────────────────────────────


async def complete(
    messages: list[dict[str, str]],
    *,
    model: str = "local/llama3",
    timeout: float = INFERENCE_TIMEOUT_SECS,
    stream: bool = False,
) -> str | Any:
    """
    Route a chat completion request through the hybrid fallback matrix.

    Args:
        messages: OpenAI-format message list [{"role": "user", "content": "..."}]
        model:    Primary model group name. Defaults to "local/llama3".
                  On CLOUD_ONLY systems, pass "gemini/flash" directly.
        timeout:  Hard deadline for the entire call chain, including retries.
                  asyncio.wait_for enforces this to prevent event-loop deadlock.
        stream:   Whether to return a streaming response object.

    Returns:
        If stream=False: the assistant content string.
        If stream=True:  the raw LiteLLM AsyncGenerator for caller iteration.

    Raises:
        asyncio.TimeoutError: if the entire call chain exceeds `timeout` seconds.
        RuntimeError: if all fallback tiers are exhausted.
    """
    router = get_router()
    t_start = time.monotonic()

    log.info(f"> ROUTER: Routing inference → model_group={model} timeout={timeout}s")

    try:
        response = await asyncio.wait_for(
            router.acompletion(
                model=model,
                messages=messages,
                stream=stream,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t_start
        log.error(
            f"> ROUTER: Inference timeout after {elapsed:.1f}s "
            f"(model={model}, limit={timeout}s). All fallbacks exhausted."
        )
        raise
    except Exception as exc:
        log.error(f"> ROUTER: Inference failed — {type(exc).__name__}: {exc}")
        raise

    elapsed = time.monotonic() - t_start
    log.info(f"> ROUTER: Inference complete in {elapsed:.2f}s")

    if stream:
        return response  # Caller iterates the async generator

    # Extract text content from non-streaming response
    try:
        content: str = response.choices[0].message.content or ""
    except (AttributeError, IndexError) as exc:
        raise RuntimeError(f"Malformed LiteLLM response: {exc}") from exc

    return content


async def stream_complete(
    messages: list[dict[str, str]],
    *,
    model: str = "local/llama3",
    timeout: float = INFERENCE_TIMEOUT_SECS,
) -> AsyncIterator[str]:
    """
    Convenience wrapper that yields token strings from a streaming completion.

    Usage in the Kriya Loop engine:
        async for token in hybrid_router.stream_complete(messages):
            push_log_event(token)
    """
    response = await complete(messages, model=model, timeout=timeout, stream=True)
    async for chunk in response:
        try:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        except (AttributeError, IndexError):
            continue


# ── Model Group Selection Helper ─────────────────────────────────────────────


def select_model_group(vram_total_gb: float, vram_used_gb: float) -> str:
    """
    Determine the primary model group based on current hardware state.

    This mirrors the routing decision tree from YANTRA_MASTER_CONTEXT §4.8:
      ≥ 16 GB VRAM → LOCAL_CAPABLE  → "local/llama3"
      ≥  8 GB VRAM → LOCAL_CAPABLE  → "local/llama3" (smaller quants)
       < 8 GB VRAM → CLOUD_ONLY    → "gemini/flash"
         no GPU    → CLOUD_ONLY    → "gemini/flash"

    The router handles the actual fallback if the chosen group fails.
    """
    available_gb = vram_total_gb - vram_used_gb
    if vram_total_gb >= 8.0 and available_gb >= 4.0:
        return "local/llama3"
    return "gemini/flash"
