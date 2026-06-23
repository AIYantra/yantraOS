"""
YantraOS — Hybrid Cognitive Router (Headless MVP - Cloud Only)

Instantiates a LiteLLM Router hardcoded to the CLOUD_ONLY pathway using Azure OpenAI.

Fallback chain:
  Primary: azure/gpt-5.4-mini
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import os
import time
from typing import Any, AsyncIterator

log = logging.getLogger("yantra.hybrid_router")

INFERENCE_TIMEOUT_SECS: float = 45.0

_INFERENCE_EXECUTOR: concurrent.futures.ThreadPoolExecutor = (
    concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="yantra-llm")
)

class InferenceAuthError(Exception):
    """Raised when an inference call fails due to an authentication/API key error."""
    pass

_router_instance: Any = None


def _build_router() -> Any:
    """Construct the LiteLLM Router for cloud-only fallback."""
    try:
        import litellm  # type: ignore
        from litellm import Router  # type: ignore
    except ImportError as exc:
        raise RuntimeError("litellm is not installed.") from exc

    litellm.suppress_debug_info = True
    litellm.set_verbose = False

    _CLOUD_REQUEST_TIMEOUT_SECS: int = 30

    model_list: list[dict[str, Any]] = [
        {
            "model_name": "azure/gpt-5.4-mini",
            "litellm_params": {
                "model": "azure/gpt-5.4-mini",
                "api_key": os.environ.get("AZURE_API_KEY", ""),
                "api_base": os.environ.get("AZURE_API_BASE", ""),
                "api_version": os.environ.get("AZURE_API_VERSION", "2024-02-15-preview"),
                "timeout": _CLOUD_REQUEST_TIMEOUT_SECS,
                "stream": True,
            },
        },
    ]

    fallbacks = []

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

    log.info("> ROUTER: LiteLLM Router initialized (CLOUD_ONLY)")
    return router


def get_router() -> Any:
    global _router_instance
    if _router_instance is None:
        _router_instance = _build_router()
    return _router_instance


def detect_hardware_capability() -> str:
    return "CLOUD_ONLY"


async def complete(
    messages: list[dict[str, str]],
    *,
    model: str = "azure/gpt-5.4-mini",
    timeout: float = INFERENCE_TIMEOUT_SECS,
    stream: bool = False,
) -> str | Any:
    router = get_router()
    t_start = time.monotonic()
    loop = asyncio.get_running_loop()

    log.info(f"> ROUTER: Routing inference → model_group={model} timeout={timeout}s")

    try:
        _call = functools.partial(
            router.completion,
            model=model,
            messages=messages,
            stream=stream,
        )
        response = await asyncio.wait_for(
            loop.run_in_executor(_INFERENCE_EXECUTOR, _call),
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
        if "auth" in exc_name.lower() or "auth" in exc_str or "api key" in exc_str or "api_key_invalid" in exc_str or "401" in exc_str or "403" in exc_str:
            log.error(f"> ROUTER: Authentication failure — {exc_name}: {exc}")
            raise InferenceAuthError(f"Authentication failed on {model}: {exc}") from exc
        log.error(f"> ROUTER: Inference failed — {exc_name}: {exc}")
        raise

    elapsed = time.monotonic() - t_start
    log.info(f"> ROUTER: Inference complete in {elapsed:.2f}s")

    if stream:
        return response

    try:
        content: str = response.choices[0].message.content or ""
    except (AttributeError, IndexError) as exc:
        raise RuntimeError(f"Malformed LiteLLM response: {exc}") from exc

    return content


async def stream_complete(
    messages: list[dict[str, str]],
    *,
    model: str = "azure/gpt-5.4-mini",
    timeout: float = INFERENCE_TIMEOUT_SECS,
) -> AsyncIterator[str]:
    response = await complete(messages, model=model, timeout=timeout, stream=True)
    loop = asyncio.get_running_loop()
    _SENTINEL: object = object()

    def _next_chunk() -> Any:
        return next(iter_ref, _SENTINEL)

    iter_ref = iter(response)
    while True:
        chunk = await loop.run_in_executor(_INFERENCE_EXECUTOR, _next_chunk)
        if chunk is _SENTINEL:
            break
        try:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        except (AttributeError, IndexError):
            continue
        await asyncio.sleep(0)


def select_model_group(vram_total_gb: float, vram_used_gb: float) -> str:
    return "azure/gpt-5.4-mini"
