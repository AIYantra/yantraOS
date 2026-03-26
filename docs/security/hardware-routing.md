# Hardware Routing & Fallbacks

YantraOS solves the "AI Accessibility Gap" through a strictly enforced, dynamic **Hybrid Inference Router** (`core/hybrid_router.py`). 

To bring autonomous agents to legacy hardware, the Kriya Loop cannot stubbornly rely on a singular local LLM context. It must shift inference to the cloud when local hardware saturates or falls below threshold requirements. 

## The Abstraction Layer (`core/hardware.py`)

At boot, the Kriya Loop evaluates the environment using `pynvml` (for NVIDIA telemetry) and native `/sys/class/drm` or `lspci` calls to profile the active integrated or discrete GPU architecture.

### Detection Thresholds

1. **`LOCAL_CAPABLE`**
   If the daemon detects an NVIDIA RTX or AMD Radeon GPU with **&ge; 8GB of VRAM**, the OS enters `LOCAL_CAPABLE` mode. The primary routing path points to a local, air-gapped `ollama` instance (e.g., `llama3:8b`). Latency is minimized, and privacy is absolute—not a single byte of telemetry goes to the cloud.

2. **`CLOUD_ONLY`**
   If the daemon detects Intel integrated graphics, a legacy GPU, or VRAM strictly `< 8GB`, the node is declared `CLOUD_ONLY`. The local daemon will bypass `ollama` entirely and rely on external APIs (Gemini 2.0 Flash / Claude 3.5 Haiku) for heavy logic execution.

## The Hybrid Inference Router

When the `ACT` phase invokes an LLM, the `router.py` script utilizes the `LiteLLM` library to manage API load balancing and fallbacks automatically.

### Graceful Fallbacks

Even in `LOCAL_CAPABLE` mode, a local GPU can be overwhelmed. If the `ollama` container returns an HTTP timeout or memory saturation error, the LiteLLM Router instantly pivots calculation to the secondary cloud tier.

```python
# core/hybrid_router.py
response = litellm.completion(
    model="ollama/llama3",
    messages=context,
    fallbacks=["gemini/gemini-2.5-flash", "claude-3-5-haiku-20241022"],
    timeout=_CLOUD_REQUEST_TIMEOUT_SECS
)
```

### The 30-Second Timeout Invariant

The Kriya Loop must never hang. Network instability, DNS blocks, or external API rotation must not lock the host Arch instance.

To guarantee this, YantraOS enforces a rigid timeout:
`_CLOUD_REQUEST_TIMEOUT_SECS = 30`

If the secondary cloud target (e.g., Google or Anthropic API) fails to stream a token or resolve a payload within 30 seconds, LiteLLM raises a `Timeout` exception.

The daemon traps the timeout, sets `daemon_status="ERROR"`, invokes the `ANALYZE` phase to document the network latency, and rotates the configuration model down the fallback array for the next query. The host system remains stable.

## Polkit Authority

Hardware profiling often demands elevated privileges (`cap_sys_admin` or root `sudo`). YantraOS executes as the unprivileged `yantra_daemon`. 

Instead of running the router as root, explicit **Polkit rules** (`/etc/polkit-1/rules.d/`) are crafted to whitelist read-only access to specific structural interfaces (like `btrfs` snapshot states) without granting carte-blanche root. This is the cornerstone of native Arch Linux stability.
