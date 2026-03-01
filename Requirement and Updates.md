# YantraOS Web HUD: Final System Requirements & Update Matrix (yantraos.com)

**ANALYSIS REPORT: local directory (`/home/admin/Documents/YantraOS`)**
The local directory has been deeply analyzed. It contains the Arch Linux Daemon (`core/`, `ui/`, `deploy/`) and the central architecting source of truth: `YANTRA_MASTER_CONTEXT.md`. The actual next.js web code is in a separate private repository `osyantra/yantraos-web-hud` deployed to Vercel at `https://yantraos.com`.

The following represents the rigid update matrix derived directly from the Master Context to synchronize the Web HUD with the native Kriya Loop.

## 1. Frontend Compliance & Geometric Law
The entire web interface at `yantraos.com` MUST strictly adhere to the following:
*   **The Geometric Law (INVIOLABLE):** All UI components rendering the telemetry must enforce `borderRadius: 0px` everywhere (no `rounded-md`, strict squares).
*   **Design Tokens:** Base `#1E1E1E` (Surface) / `#2A2A2A` (Panels) / `#00E5FF` (Electric Blue Accent) / `#FFB000` (Terminal Amber). Hover states should have instant snap (no transitions).
*   **Typography:** JetBrains Mono for all terminal/code, Inter for body text.

## 2. API Route Engineering (Next.js 14 App Router)
The Vercel deployment must expose the following routes securely:

| Component / Route | Tech / Protocol | Strict Requirement | Status |
| :--- | :--- | :--- | :--- |
| `/api/telemetry/ingest` (POST) | JSON POST | **Must validate exact `yantraos/telemetry/v1` schema.** Extract properties like `active_model`, `inference_routing` (e.g., `CLOUD_ONLY` for the Zenbook), `vram_usage`, and `current_cycle`. Requires Bearer auth token syncing with `yantra.service`. | ⚠️ CRITICAL UPDATE REQUIRED |
| `/api/kriya/execute` (POST) | `@ai-sdk/google` | Since the laptop falls back to `CLOUD_ONLY`, this acts as the **Secure API Gateway**. Must map requests via Vercel AI SDK to Gemini 2.0 Flash (`gemini-2.0-flash`) and stream reasoning back to the local daemon. | ⚠️ CRITICAL UPDATE REQUIRED |
| `/api/health` (GET) | Fetch + JSON | Merge live Kriya Cache values + Pinecone Vector Database health logic to verify the semantic RAG memory layer is online. | 🔲 Verification Needed |
| `/api/skills/search` (GET) | `@pinecone-database/pinecone` | Execute `yantra-skills` RAG queries passing `?query=X` to retrieve skill endpoints for execution. | 🔲 Pending Implementation |

## 3. Streaming UI Elements (Pages & Components)
The root path (`/`) requires the following components receiving live Real-Time telemetry updates via WebSocket/SSE polling from `/api/telemetry/ingest`:

*   **`TelemetryStrip`**: Live indicators mapping directly to the daemon data: PINECONE state, ROUTING logic, active MODEL.
*   **`TerminalHUD`**: Interactive boot sequence and autonomous logs directly bridging to the `ThoughtStream` on the host machine.
*   **`EngineRoom`**: 3-Card structure (CORE-01: Hybrid Inference, CORE-02: Vector Memory, CORE-03: Atomic Stability) using `EvervaultCard` overlays.
*   **`/skill-store` (New Page)**: Will render JSON based on the `yantraos/skill/v1` schema allowing users to browse/acquire autonomous behaviors.

## 4. Final Verification Criteria
Before pushing the Web HUD payload, ensure:
1.  All endpoint payloads match the strict JSON schemas enforced in `YANTRA_MASTER_CONTEXT.md` (e.g., `vram_usage` dict has `used_gb`, `total_gb`, `percent`).
2.  `GOOGLE_GENERATIVE_AI_API_KEY` (NOT `GEMINI_API_KEY`) is active in Vercel to route remote operations.
