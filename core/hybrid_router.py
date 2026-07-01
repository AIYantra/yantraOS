"""
YantraOS — Hybrid Cognitive Router (Headless MVP - Cloud Only)

Instantiates a LiteLLM Router hardcoded to the CLOUD_ONLY pathway using Azure OpenAI.

Fallback chain:
  Primary: azure/deepseek-v4-flash
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

    secrets_path = "/etc/yantra/host_secrets.env"
    if os.path.exists(secrets_path):
        with open(secrets_path, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, val = line.strip().split("=", 1)
                    os.environ[key] = val
                    if key == "DEEPSEEK_API_KEY":
                        os.environ["OPENAI_API_KEY"] = val
                    if key == "DEEPSEEK_API_BASE":
                        os.environ["OPENAI_API_BASE"] = val

    litellm.suppress_debug_info = True
    litellm.set_verbose = False

    _CLOUD_REQUEST_TIMEOUT_SECS: int = 30

    model_list: list[dict[str, Any]] = [
        {
            "model_name": "azure/gpt-5.4-mini",
            "litellm_params": {
                "model": "azure/gpt-5.4-mini",
                "api_key": os.environ.get("AZURE_OPENAI_API_KEY", ""),
                "api_base": os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
                "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", "2026-03-17"),
                "timeout": _CLOUD_REQUEST_TIMEOUT_SECS,
                "stream": True,
            },
        },
        {
            "model_name": "local/deepseek-v4",
            "litellm_params": {
                "model": "openai/deepseek-v4",
                "api_key": os.environ.get("BUILDER_API_KEY", "dummy"),
                "api_base": os.environ.get("BUILDER_API_BASE", "http://host.docker.internal:8000/v1"),
                "timeout": 120,
                "stream": True,
            },
        },
        {
            "model_name": "gemini/gemini-2.0-flash",
            "litellm_params": {
                "model": "gemini/gemini-2.0-flash",
                "api_key": os.environ.get("GEMINI_API_KEY", ""),
                "timeout": 30,
                "stream": True,
            },
        },
        {
            "model_name": "anthropic/claude-3-5-sonnet",
            "litellm_params": {
                "model": "anthropic/claude-3-5-sonnet",
                "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
                "timeout": 30,
                "stream": True,
            },
        },
    ]

    fallbacks = [
        {"model": "gemini/gemini-2.0-flash"},
        {"model": "anthropic/claude-3-5-sonnet"}
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

    log.info("> ROUTER: LiteLLM Router initialized (Hybrid Tiered)")
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
    cognitive_tier: str = "watchdog",
    timeout: float = INFERENCE_TIMEOUT_SECS,
    stream: bool = False,
) -> str | Any:
    router = get_router()
    t_start = time.monotonic()
    loop = asyncio.get_running_loop()

    if cognitive_tier == "builder":
        model = "local/deepseek-v4"
    else:
        model = "azure/gpt-5.4-mini"

    log.info(f"> ROUTER: Routing inference → tier={cognitive_tier} model_group={model} timeout={timeout}s")

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
    cognitive_tier: str = "watchdog",
    timeout: float = INFERENCE_TIMEOUT_SECS,
) -> AsyncIterator[str]:
    response = await complete(messages, cognitive_tier=cognitive_tier, timeout=timeout, stream=True)
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
