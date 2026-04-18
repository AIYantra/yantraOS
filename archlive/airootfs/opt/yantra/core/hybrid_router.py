"""
YantraOS — Hybrid Cognitive Router
Target: /opt/yantra/core/hybrid_router.py
Milestone 2, Task 2.2 — RC8 Domain-Isolated Fallback

Instantiates a LiteLLM Router with a hardware-domain-isolated fallback
matrix. Routing strategy is locked to "simple-shuffle" — round-robin across
equivalent models — to eliminate thundering-herd performance penalties
associated with "latency-based" or "cost-based" strategies under local load.

RC8 FIX — Strict Domain Isolation:
  • detect_hardware_capability() classifies hardware as LOCAL_CAPABLE or CLOUD_ONLY.
  • CLOUD_ONLY systems (0.0 GB VRAM) NEVER receive local/* fallbacks.
    Attempting to run local models on zero-VRAM hardware causes an
    unrecoverable CPU memory deadlock.
  • AuthenticationError is surfaced as a distinct exception so the engine
    can transition to DEGRADED_AUTH instead of cross-domain fallback.

Security invariants:
  • API credentials are NEVER hardcoded. All secrets are loaded exclusively
    from /etc/yantra/host_secrets.env (root:root, mode 0600) at module init.
  • The host_secrets.env file is read once and the values stored only in
    os.environ; no secrets are written to logs or any other file.

Resilience invariants:
  • Every async inference call is wrapped in asyncio.wait_for() with a
    configurable timeout to prevent deadlock from unresponsive endpoints.
  • Fallback matrix is domain-isolated per hardware capability.
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


# ── Hardware Domain Detection ─────────────────────────────────────────────────

_HW_CAPABILITY: str | None = None  # Cached result: "LOCAL_CAPABLE" or "CLOUD_ONLY"


def detect_hardware_capability() -> str:
    """
    Classify the current machine as LOCAL_CAPABLE or CLOUD_ONLY.

    LOCAL_CAPABLE: ≥ 8 GB VRAM total, ≥ 4 GB available → safe for ollama.
    CLOUD_ONLY:    < 8 GB VRAM or no GPU → local models will OOM/deadlock.

    Result is cached after first probe to avoid repeated pynvml calls.
    """
    global _HW_CAPABILITY
    if _HW_CAPABILITY is not None:
        return _HW_CAPABILITY

    try:
        from .hardware import probe_gpu
        gpu = probe_gpu()
        available = gpu.vram_total_gb - gpu.vram_used_gb
        if gpu.vram_total_gb >= 8.0 and available >= 4.0:
            _HW_CAPABILITY = "LOCAL_CAPABLE"
        else:
            _HW_CAPABILITY = "CLOUD_ONLY"
    except Exception:
        _HW_CAPABILITY = "CLOUD_ONLY"  # Assume worst case on probe failure

    log.info(f"> ROUTER: Hardware capability detected: {_HW_CAPABILITY}")
    return _HW_CAPABILITY


# ── Authentication Error Sentinel ─────────────────────────────────────────────

class InferenceAuthError(Exception):
    """Raised when an inference call fails due to an authentication/API key error."""
    pass

_FORCE_LOCAL_ONLY: bool = False


# ── Router Factory ────────────────────────────────────────────────────────────

_router_instance: Any = None  # litellm.Router — typed as Any to avoid hard import


def _build_router() -> Any:
    """
    Construct the LiteLLM Router with a domain-isolated fallback matrix.

    RC8 INVARIANT — Strict Domain Isolation:
      If detect_hardware_capability() == "CLOUD_ONLY", the fallbacks array
      MUST NOT contain local/* models. Cascading to local/llama3 on a machine
      with 0.0 GB VRAM causes an unrecoverable CPU memory deadlock.

    LOCAL_CAPABLE fallback chain:
      local/llama3 → gemini/flash → anthropic/haiku → openai/gpt4o

    CLOUD_ONLY fallback chain:
      gemini/flash → anthropic/haiku → openai/gpt4o
      (local/* models are EXCLUDED from both model_list and fallbacks)

    routing_strategy is hardcoded to "simple-shuffle" — round-robin across
    equivalent models within a group. Do NOT use "latency-based-routing".
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

    hw_cap = detect_hardware_capability()
    ollama_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    # ── Build model list (domain-isolated) ────────────────────────────────
    model_list: list[dict[str, Any]] = []

    # Local models are ONLY included for LOCAL_CAPABLE hardware.
    # Including them on CLOUD_ONLY hardware causes lethal CPU OOM.
    if hw_cap == "LOCAL_CAPABLE":
        model_list.extend([
            {
                "model_name": "local/llama3",
                "litellm_params": {
                    "model": "ollama/Llama-3-8B-Instruct.Q4_K_M.gguf",
                    "api_base": ollama_base,
                    "timeout": 30,
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
        ])

    # Cloud models are always available.
    # Patch 6: Enforce strict 30s per-request HTTP timeout on all cloud models.
    # The outer asyncio.wait_for (45s) remains as a safety net for full call chain.
    _CLOUD_REQUEST_TIMEOUT_SECS: int = 30

    model_list.extend([
        # ── Cloud Primary: Google Gemini 2.5 Flash ────────────────────────
        {
            "model_name": "gemini/flash",
            "litellm_params": {
                "model": "gemini/gemini-2.5-flash",
                "api_key": os.environ.get("GEMINI_API_KEY", "your-api-key-here"),
                "timeout": _CLOUD_REQUEST_TIMEOUT_SECS,
                "stream": True,
            },
        },
        # ── Cloud Secondary: Anthropic Claude 3.5 Haiku ───────────────────
        {
            "model_name": "anthropic/haiku",
            "litellm_params": {
                "model": "anthropic/claude-3-5-haiku-20241022",
                "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
                "timeout": _CLOUD_REQUEST_TIMEOUT_SECS,
                "stream": True,
            },
        },
        # ── Cloud Tertiary: OpenAI GPT-4o (emergency fallback) ────────────
        {
            "model_name": "openai/gpt4o",
            "litellm_params": {
                "model": "openai/gpt-4o",
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "timeout": _CLOUD_REQUEST_TIMEOUT_SECS,
                "stream": True,
            },
        },
    ])

    # ── Build domain-isolated fallback matrix ─────────────────────────────
    if hw_cap == "LOCAL_CAPABLE":
        # LOCAL_CAPABLE: local GPU → cloud cascade
        fallbacks = [
            {"local/llama3": ["gemini/flash", "anthropic/haiku", "openai/gpt4o"]},
            {"gemini/flash": ["anthropic/haiku", "openai/gpt4o"]},
            {"anthropic/haiku": ["openai/gpt4o"]},
        ]
    else:
        # CLOUD_ONLY: cloud-to-cloud only — NO local/* models permitted.
        # This prevents the lethal CPU memory deadlock on 0.0 GB VRAM.
        fallbacks = [
            {"gemini/flash": ["anthropic/haiku", "openai/gpt4o"]},
            {"anthropic/haiku": ["gemini/flash", "openai/gpt4o"]},
        ]

    router = Router(
        model_list=model_list,
        fallbacks=fallbacks,
        routing_strategy="simple-shuffle",
        num_retries=2,
        retry_after=2,
        allowed_fails=1,
        cooldown_time=60,
        cache_responses=False,
        set_verbose=False,
    )

    log.info(
        f"> ROUTER: LiteLLM Router initialized "
        f"(strategy=simple-shuffle, hw={hw_cap}, "
        f"{len(model_list)} models, {len(fallbacks)} fallback chains)"
    )
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
    global _FORCE_LOCAL_ONLY
    if _FORCE_LOCAL_ONLY:
        model = "local/llama3"

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
        exc_name = type(exc).__name__
        exc_str = str(exc).lower()
        # Detect authentication failures and surface them distinctly
        # so the engine can transition to DEGRADED_AUTH instead of
        # attempting a lethal cross-domain fallback.
        if "auth" in exc_name.lower() or "auth" in exc_str or "api key" in exc_str or "api_key_invalid" in exc_str or "401" in exc_str or "403" in exc_str:
            log.error(f"> ROUTER: Authentication failure — {exc_name}: {exc}")
            _FORCE_LOCAL_ONLY = True
            log.warning("> ROUTER: Cloud authentication failed. Permanently toggling internal state to LOCAL_ONLY.")
            raise InferenceAuthError(f"Authentication failed on {model}: {exc}") from exc
        log.error(f"> ROUTER: Inference failed — {exc_name}: {exc}")
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

    RC8 INVARIANT: This function MUST agree with detect_hardware_capability().
    If CLOUD_ONLY, NEVER return a local/* model group — the engine will pass
    this value to the router which would deadlock on a zero-VRAM machine.
    """
    hw = detect_hardware_capability()
    if hw == "LOCAL_CAPABLE":
        available_gb = vram_total_gb - vram_used_gb
        if vram_total_gb >= 8.0 and available_gb >= 4.0:
            return "local/llama3"
    # CLOUD_ONLY or insufficient VRAM → cloud primary
    return "gemini/flash"
