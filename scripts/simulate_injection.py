#!/usr/bin/env python3
import asyncio
import json
import datetime
import websockets

# --- YANTRA UI AESTHETIC COLORS ---
ANSI_BLUE = "\033[36m"
ANSI_AMBER = "\033[33m"
ANSI_GREEN = "\033[32m"
ANSI_RESET = "\033[0m"

async def simulate_injection():
    uri = "ws://127.0.0.1:50000/stream"
    print(f"{ANSI_BLUE}[YANTRA_HUD] INITIATING DIAGNOSTIC PROBE OVER IPC BRIDGE -> {uri}{ANSI_RESET}")

    # The Payload Profile: Design a benign "Diagnostics Probe" skill complying with yantraos/skill/v1
    skill_payload = {
        "command": "INJECT_SKILL",
        "skill_id": "mock-diag-001",
        "daemon_hook": "import os, platform; print(f'Sandbox active on {platform.system()}')",
        "execution_environment": {
            "type": "local_sandbox",
            "requires_vram_gb": None,
            "supported_models": [],
            "daemon_hook": "import os, platform; print(f'Sandbox active on {platform.system()}')"
        },
        "full_schema": {
            "$schema": "yantraos/skill/v1",
            "id": "mock-diag-001",
            "title": "Amnesia Sandbox Diagnostics Probe",
            "description": "A synthetic validation probe verifying docker orchestration sequences over IPC.",
            "version": "1.0.0",
            "icon_reference": "terminal",
            "tags": ["diagnostics", "sandbox", "probe"],
            "category": "utility",
            "execution_environment": {
                "type": "local_sandbox",
                "requires_vram_gb": None,
                "supported_models": [],
                "daemon_hook": "import os, platform; print(f'Sandbox active on {platform.system()}')"
            },
            "pinecone_metadata": {
                "index_name": "yantra-skills",
                "namespace": "mock_test",
                "vector_dimensions": 1536
            },
            "author": "YantraOS Master Controller",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "is_public": False,
            "download_count": 0
        }
    }

    try:
        # Utilize the standard websockets and asyncio libraries
        async with websockets.connect(uri) as websocket:
            print(f"{ANSI_GREEN}[SYSTEM_ACK] SECURE HANDSHAKE ESTABLISHED WITH KRIYA DAEMON.{ANSI_RESET}")
            
            # Serialize and transmit
            print(f"{ANSI_BLUE}[TX] TRANSMITTING VALIDATED yantraos/skill/v1 PAYLOAD (Skill ID: mock-diag-001)...{ANSI_RESET}")
            pack = json.dumps(skill_payload)
            await websocket.send(pack)

            # Await and print the daemon's response
            print(f"{ANSI_AMBER}[AWAITING EXECUTION METRICS...] {ANSI_RESET}")
            response = await websocket.recv()
            
            # Parse response
            try:
                parsed = json.loads(response)
                print(f"{ANSI_GREEN}[RX_JSON] DAEMON RESPONSE: {json.dumps(parsed, indent=2)}{ANSI_RESET}")
            except json.JSONDecodeError:
                print(f"{ANSI_GREEN}[RX_TEXT] DAEMON RESPONSE: {response}{ANSI_RESET}")

    except ConnectionRefusedError:
        print(f"{ANSI_AMBER}[CRITICAL FAULT] CONNECTION REFUSED: Ensure yantra.service is active on 127.0.0.1:50000.{ANSI_RESET}")
    except websockets.exceptions.InvalidURI:
         print(f"{ANSI_AMBER}[CRITICAL FAULT] UNREACHABLE IPC NODE: {uri}{ANSI_RESET}")
    except Exception as e:
        print(f"{ANSI_AMBER}[CRITICAL FAULT] UNEXPECTED ANOMALY: {e}{ANSI_RESET}")

if __name__ == "__main__":
    try:
        asyncio.run(simulate_injection())
    except KeyboardInterrupt:
        print(f"\n{ANSI_AMBER}[ABORTED] DIAGNOSTIC PROBE TERMINATED BY OPERATOR INTERVENTION.{ANSI_RESET}")