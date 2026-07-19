"""YantraOS hybrid cognitive router for Azure Foundry and local fallback."""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import os
import time
from typing import Any, AsyncIterator

log = logging.getLogger("yantra.hybrid_router")

INFERENCE_TIMEOUT_SECS: float = 180.0

# Critical Decoupling: ThreadPoolExecutor with max_workers=4
_INFERENCE_EXECUTOR: concurrent.futures.ThreadPoolExecutor = (
    concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="yantra-llm")
)

class InferenceAuthError(Exception):
    pass

class TieredRouter:
    LUNA = "azure/gpt-5.6-luna"
    TERRA = "azure/gpt-5.6-terra"
    SOL = "azure/gpt-5.6-sol"

    # Cloud-hosted model identifiers — any model NOT in this set is LOCAL.
    _CLOUD_MODELS = frozenset({LUNA, TERRA, SOL})
    _CLOUD_FALLBACKS = {
        SOL: TERRA,
        TERRA: LUNA,
    }

    def __init__(self):
        try:
            import litellm  # type: ignore
            from litellm import Router  # type: ignore
        except ImportError as exc:
            raise RuntimeError("litellm is not installed.") from exc

        self.litellm = litellm
        self.litellm.suppress_debug_info = True
        self.litellm.set_verbose = False
        
        self.local_only_mode = False
        self.last_routing_tier: str = "LOCAL"  # Updated after every successful completion

        raw_base = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        if raw_base:
            if "/chat/completions" in raw_base:
                api_base_url = raw_base.split("/chat/completions")[0]
            elif not raw_base.endswith("/v1"):
                api_base_url = raw_base.rstrip("/") + "/v1" if "/openai" in raw_base else raw_base
            else:
                api_base_url = raw_base
        else:
            api_base_url = ""

        azure_deployments = {
            self.LUNA: os.environ.get("AZURE_DEPLOYMENT_LUNA", "gpt-5.6-luna"),
            self.TERRA: os.environ.get("AZURE_DEPLOYMENT_TERRA", "gpt-5.6-terra"),
            self.SOL: os.environ.get("AZURE_DEPLOYMENT_SOL", "gpt-5.6-sol"),
        }
        api_key = os.environ.get("YANTRA_AZURE_KEY", os.environ.get("AZURE_OPENAI_API_KEY", ""))

        model_list = [
            {
                "model_name": model_name,
                "litellm_params": {
                    "model": f"openai/{deployment}",
                    "api_key": api_key,
                    "api_base": api_base_url,
                    "timeout": 300,
                    "stream": True,
                },
            }
            for model_name, deployment in azure_deployments.items()
        ] + [
            {
                "model_name": "local/deepseek-v4",
                "litellm_params": {
                    "model": "openai/deepseek-v4",
                    "api_key": os.environ.get("BUILDER_API_KEY", "dummy"),
                    "api_base": os.environ.get("BUILDER_API_BASE", "http://host.docker.internal:8000/v1"),
                    "timeout": 120,
                    "stream": True,
                },
            }
        ]

        self.router = Router(
            model_list=model_list,
            routing_strategy="simple-shuffle",
            num_retries=1,
            cache_responses=False,
            set_verbose=False,
        )
        log.info("> ROUTER: TieredRouter initialized")

    def _get_model_for_phase(self, phase: str) -> str:
        if self.local_only_mode:
            return "local/deepseek-v4"

        phase = phase.upper()
        # Callers can mark novel or ambiguous work explicitly for escalation.
        if phase in ("SENSE", "TEST", "WATCHDOG"):
            return self.LUNA
        elif phase in ("NOVEL", "AMBIGUOUS", "BUILDER", "SOL"):
            return self.SOL
        elif phase in ("REASON", "ACT", "TERRA"):
            return self.TERRA
        else:
            return self.LUNA

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        cognitive_tier: str = "SENSE",
        timeout: float = INFERENCE_TIMEOUT_SECS,
        stream: bool = False,
    ) -> Any:
        loop = asyncio.get_running_loop()
        model = self._get_model_for_phase(cognitive_tier)

        log.info(f"> ROUTER: Routing inference → phase={cognitive_tier} model={model} timeout={timeout}s")

        try:
            _call = functools.partial(
                self.router.completion,
                model=model,
                messages=messages,
                stream=stream,
            )
            # Decoupled network call running in thread pool executor
            response = await asyncio.wait_for(
                loop.run_in_executor(_INFERENCE_EXECUTOR, _call),
                timeout=timeout,
            )
            # ── Routing tier tracking ──────────────────────────────────────
            self.last_routing_tier = "CLOUD" if model in self._CLOUD_MODELS else "LOCAL"
            return response
        except asyncio.TimeoutError:
            log.error(f"> ROUTER: Inference timeout (model={model}, limit={timeout}s).")
            raise
        except Exception as exc:
            exc_str = str(exc).lower()
            if any(k in exc_str for k in ["auth", "api key", "401", "403"]):
                log.error(f"> ROUTER: Authentication failure on {model}. Gracefully degrading to LOCAL_ONLY mode.")
                self.local_only_mode = True
                if model != "local/deepseek-v4":
                    log.info("> ROUTER: Retrying with local model...")
                    return await self.complete(messages, cognitive_tier=cognitive_tier, timeout=timeout, stream=stream)
                raise InferenceAuthError(f"Auth failed and no local fallback available: {exc}") from exc
            fallback_model = self._CLOUD_FALLBACKS.get(model)
            if fallback_model is not None:
                log.warning(f"> ROUTER: Cloud model ({model}) failed ({exc}). Falling back to {fallback_model}...")
                _fallback_call = functools.partial(
                    self.router.completion,
                    model=fallback_model,
                    messages=messages,
                    stream=stream,
                )
                try:
                    fb_response = await asyncio.wait_for(
                        loop.run_in_executor(_INFERENCE_EXECUTOR, _fallback_call),
                        timeout=timeout,
                    )
                    self.last_routing_tier = "CLOUD"
                    return fb_response
                except Exception as fb_exc:
                    log.error(f"> ROUTER: Fallback to {fallback_model} also failed: {fb_exc}")
            log.error(f"> ROUTER: Inference failed: {exc}")
            raise

_router_instance: TieredRouter | None = None

def get_router() -> TieredRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = TieredRouter()
    return _router_instance

def detect_hardware_capability() -> str:
    router = get_router()
    return "LOCAL_ONLY" if router.local_only_mode else "HYBRID"

def get_last_routing_tier() -> str:
    """Return the routing tier used by the last successful completion: 'CLOUD' or 'LOCAL'."""
    router = get_router()
    return router.last_routing_tier

async def complete(
    messages: list[dict[str, str]],
    *,
    cognitive_tier: str = "SENSE",
    timeout: float = INFERENCE_TIMEOUT_SECS,
    stream: bool = False,
) -> str | Any:
    router = get_router()
    t_start = time.monotonic()
    
    response = await router.complete(
        messages, cognitive_tier=cognitive_tier, timeout=timeout, stream=stream
    )
    
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
    cognitive_tier: str = "SENSE",
    timeout: float = INFERENCE_TIMEOUT_SECS,
) -> AsyncIterator[str]:
    content = await complete(messages, cognitive_tier=cognitive_tier, timeout=timeout, stream=False)
    if isinstance(content, str):
        yield content
    else:
        try:
            text = content.choices[0].message.content or ""
            yield text
        except Exception:
            yield str(content)

def select_model_group(vram_total_gb: float, vram_used_gb: float) -> str:
    return TieredRouter.LUNA
