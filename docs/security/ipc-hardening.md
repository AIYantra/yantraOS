# IPC Bridge Hardening

The **IPC Bridge** (Inter-Process Communication) is the nervous system of YantraOS, connecting the autonomous Daemon to the user-facing HUD and remote gateways like the Telegram C2 server. 

Because the Daemon has the capability to execute root-level system intents and spawn arbitrary sandboxed malware analysis containers, securing the IPC bridge against malicious interception or injection is paramount.

## Defense in Depth

YantraOS implements a strict defense-in-depth model for the internal network layer.

### 1. Localhost Enforcement

All privileged IPC endpoints (such as `/inject`, `/api/v1/config/route`, and `/api/v1/secrets/update`) are strictly bound to `127.0.0.1`. 

If the Daemon port (`50000`) is accidentally exposed to the broader local network or the internet (e.g., due to a misconfigured firewall or Docker port mapping), the IPC Server will actively reject any incoming requests that do not originate from the loopback interface itself. This prevents remote prompt injection or system hijacking.

### 2. Data Minimization (Pydantic Strict Mode)

To prevent payload smuggling or advanced injection attacks, all incoming JSON payloads are heavily validated using Pydantic models with `extra = "forbid"` configuration.

Any undocumented or extra keys injected into a payload (for example, attempting to smuggle an `action` key into an `InjectCommand` payload) will immediately trigger a `422 Unprocessable Entity` validation error, dropping the request before it even reaches the engine logic.

## Telegram Gateway Isolation

To adhere to the principle of Separation of Concerns, the core Daemon does not communicate directly with the Telegram API. Instead, it exposes a local `/notifications` queue endpoint.

The independent Telegram Gateway service running on the host securely polls this local endpoint. This isolates the core Daemon from internet-facing API keys and external network dependencies, ensuring the Kriya Loop can continue operating completely air-gapped if required.
