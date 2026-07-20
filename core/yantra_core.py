import os
import sys
import json
import subprocess
import logging
import socket
import stat
import struct
from typing import List, Dict, Any
from openai import OpenAI

try:
    from .computer_use_bridge import run_intent as run_external_action, select_task_route
except ImportError:
    from computer_use_bridge import run_intent as run_external_action, select_task_route

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)

log = logging.getLogger("yantra.core")

SYSTEM_PROMPT = """You are YantraOS, a self-healing Linux ops daemon and general-purpose natural-language OS agent.
Your job is to translate natural language queries into a sequence of actionable intents.

You MUST output ONLY a JSON array of action objects. Do not include markdown formatting, backticks, or conversational text.
Your response will be parsed directly by `json.loads()`.

Available actions and their JSON schemas:

1. Open a URL in a browser:
{
  "action": "open_url",
  "url": "<the_url>"
}

2. Navigate and extract information:
{
  "action": "navigate_and_extract",
  "url": "<url_to_visit>",
  "instruction": "<what_to_extract>",
  "output_path": "<file_path_to_save>"
}

3. Execute an OS-level computer automation task (e.g. download, install, open apps, click, type):
{
  "action": "computer_use_task",
  "instruction": "<detailed_instruction_of_what_to_do_on_the_computer>"
}

4. Manage files inside the YantraOS managed directory with KDE Dolphin:
{
  "action": "file_management",
  "operation": "create|move|read",
  "path": "<visible_relative_path>",
  "destination": "<required_only_for_move>",
  "content": "<optional_only_for_create>"
}
Deletion, absolute paths, hidden paths, traversal, and overwrites are prohibited.
For create, emit only action, operation, path, and content.
For read, emit only action, operation, and path.
For move, emit only action, operation, path, and destination.
Always use file_management for a user's create, read, or move request.

Example valid response:
[
  {
    "action": "navigate_and_extract",
    "url": "https://en.wikipedia.org/wiki/Main_Page",
    "instruction": "read the exact title of 'Today's featured article'",
    "output_path": "/tmp/extract1.txt"
  }
]
"""

def get_openai_client() -> OpenAI:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    
    if not endpoint:
        log.error("Missing Azure OpenAI credentials. Please set AZURE_OPENAI_ENDPOINT.")
        sys.exit(1)
        
    token_provider = None
    if not api_key:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        log.info("No API key found in env, using DefaultAzureCredential...")
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
        api_key = token_provider
        
    headers = {}
    if isinstance(api_key, str) and not token_provider:
        # If it's a string API key, Azure requires 'api-key' header
        # The standard OpenAI client uses 'Authorization: Bearer', which Azure rejects
        headers["api-key"] = api_key

    return OpenAI(
        base_url=endpoint,
        api_key=api_key,
        default_headers=headers if headers else None
    )

def parse_llm_response(response_text: str) -> List[Dict[str, Any]]:
    # Handle potential markdown formatting in LLM output
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    elif response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
        
    try:
        actions = json.loads(response_text.strip())
        if not isinstance(actions, list):
            raise ValueError("Expected a JSON array of actions.")
        return actions
    except json.JSONDecodeError as e:
        log.error(f"LLM hallucinated invalid JSON: {e}")
        log.error(f"Raw response: {response_text}")
        return []
    except Exception as e:
        log.error(f"Error parsing LLM response: {e}")
        return []


def _send_host_request(
    action: Dict[str, Any], confirmation: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """Send one typed action to the root-owned Host Executor socket."""
    socket_path = "/run/yantra/executor.sock"
    metadata = os.lstat(socket_path)
    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != 0:
        raise ConnectionError("Host Executor socket is not root-owned.")
    if metadata.st_mode & (stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH):
        raise ConnectionError("Host Executor socket permits access by other users.")

    payload: Dict[str, Any] = {
        "intent": "EXTERNAL_ACTION",
        "target": "",
        "action_payload": action,
    }
    if confirmation is not None:
        payload["confirmation"] = confirmation
    request = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(430)
        connection.connect(socket_path)
        peer = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        _pid, uid, _gid = struct.unpack("3i", peer)
        if uid != 0:
            raise ConnectionError("Connected Host Executor peer is not root.")
        connection.sendall(request)
        response = bytearray()
        while b"\n" not in response and len(response) <= 16384:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response.extend(chunk)

    if b"\n" not in response or len(response) > 16384:
        raise RuntimeError("Host Executor returned an invalid response.")
    parsed = json.loads(bytes(response).split(b"\n", 1)[0])
    if not isinstance(parsed, dict) or parsed.get("intent") != "EXTERNAL_ACTION":
        raise RuntimeError("Host Executor response does not match the request.")
    return parsed


def _execute_host_action(action: Dict[str, Any]) -> bool:
    response = _send_host_request(action)
    if response.get("status") == "CONFIRMATION_REQUIRED":
        print(
            f"Confirm {action.get('action')}: "
            f"{action.get('path') or action.get('instruction', '')} "
            f"within {response.get('expires_in_secs', 120)} seconds [y/N]: ",
            end="",
            flush=True,
        )
        approved = sys.stdin.isatty() and input().strip().lower() in {"y", "yes"}
        response = _send_host_request(action, {
            "token": response["confirmation_token"],
            "approved": approved,
        })

    if response.get("status") == "SUCCESS":
        log.info("External action completed successfully.")
        return True
    log.error(
        "External action %s: %s",
        response.get("status", "FAILED"),
        response.get("error", "Host Executor did not provide details."),
    )
    return False

def execute_actions(
    actions: List[Dict[str, Any]], *, approve_steps: bool = False
):
    # Import the confirmation gate (M2: first 20 runs require human approval)
    try:
        from .action_confirmation import confirm_action, log_execution_outcome
    except ImportError:
        from action_confirmation import confirm_action, log_execution_outcome

    navigation_urls = {
        action.get("url")
        for action in actions
        if action.get("action") == "navigate_and_extract"
    }
    routed_actions: List[Dict[str, Any]] = []
    for action in actions:
        action_label = action.get("action")
        if action_label == "open_url" and action.get("url") in navigation_urls:
            continue
        if action_label == "open_url":
            action = {
                "action": "computer_use_task",
                "instruction": f"Open Firefox and go to {action.get('url', '')}.",
            }
        elif action_label == "navigate_and_extract":
            action = {
                "action": "computer_use_task",
                "instruction": (
                    f"Open Firefox, go to {action.get('url', '')}, and "
                    f"{action.get('instruction', '')}"
                ),
            }
        routed_actions.append(action)
    actions = routed_actions

    for idx, action_intent in enumerate(actions):
        action_label = action_intent.get('action', 'unknown')
        log.info(f"Proposed action {idx+1}/{len(actions)}: {action_label}")

        if action_label in {"file_management", "computer_use_task"}:
            try:
                route, route_reason = select_task_route(action_intent)
                log.info(
                    "REASON ROUTE: %s selected because %s.",
                    route,
                    route_reason,
                )
                if approve_steps:
                    succeeded = run_external_action(
                        action_intent, approve_steps=True
                    ) == 0
                else:
                    succeeded = run_external_action(action_intent) == 0
            except (OSError, RuntimeError, ValueError) as exc:
                log.error("Unprivileged external action failed: %s", exc)
                succeeded = False
            if not succeeded:
                log.error("Stopping remaining actions because a prerequisite failed.")
                break
            continue

        # ── Confirmation gate (audit-logs the proposal automatically) ─
        if not confirm_action(action_intent):
            log.info(f"Action {idx+1}/{len(actions)} SKIPPED (rejected or no TTY).")
            continue

        # ── Execute the action ────────────────────────────────────────
        intent_str = json.dumps(action_intent)
        log.info(f"Executing action {idx+1}/{len(actions)}: {action_label}")
        
        bridge_path = os.path.join(os.path.dirname(__file__), "foundry_action_bridge.py")

        try:
            result = subprocess.run(
                [sys.executable, bridge_path],
                input=intent_str,
                text=True,
            )
            if result.returncode == 0:
                log.info("Action succeeded (model declared done).")
                log_execution_outcome(
                    action_intent,
                    success=True,
                    result_msg="Bridge exit 0 (task completed).",
                )
            elif result.returncode == 2:
                log.warning("Action hit step cap without completing.")
                log_execution_outcome(
                    action_intent,
                    success=False,
                    error_msg="Bridge exit 2: hit step cap without model declaring done.",
                )
            elif result.returncode == 3:
                log.warning("Action was rejected by user/confirmation gate.")
                log_execution_outcome(
                    action_intent,
                    success=False,
                    error_msg="Bridge exit 3: action rejected.",
                )
            elif result.returncode == 4:
                log.warning("Action stalled after two ineffective interactive actions.")
                log_execution_outcome(
                    action_intent,
                    success=False,
                    error_msg="Bridge exit 4: no visible change after two interactive actions.",
                )
            else:
                log.error(f"Action failed with exit code {result.returncode}")
                log_execution_outcome(
                    action_intent,
                    success=False,
                    error_msg=f"Bridge exit {result.returncode}.",
                )
        except Exception as e:
            log.error(f"Failed to launch bridge subprocess: {e}")
            log_execution_outcome(
                action_intent,
                success=False,
                error_msg=f"Subprocess launch error: {e}",
            )


def process_query(query: str, *, approve_steps: bool = False):
    log.info(f"Processing query: {query}")
    
    deployment_name = os.getenv("AZURE_DEPLOYMENT_LUNA") or os.getenv(
        "AZURE_OPENAI_DEPLOYMENT_NAME"
    )
    if not deployment_name:
        log.error(
            "Missing AZURE_DEPLOYMENT_LUNA or AZURE_OPENAI_DEPLOYMENT_NAME."
        )
        sys.exit(1)
        
    client = get_openai_client()
    
    log.info("Sending request to Azure OpenAI deployment %s...", deployment_name)
    try:
        # Combine system prompt and user query since the new API uses 'input' as a single string
        combined_input = f"{SYSTEM_PROMPT}\n\nUser Query: {query}"
        
        response = client.responses.create(
            model=deployment_name,
            input=combined_input,
        )
        log.debug("Raw API response: %s", response)
        response_text = ""
        for item in response.output:
            if getattr(item, "type", "") == "message":
                response_text = "".join([c.text for c in getattr(item, "content", []) if getattr(c, "type", "") == "output_text"])
                break
                
        log.info(f"Extracted response text:\n{response_text}")
        log.info("Received response from LLM.")
        
        actions = parse_llm_response(response_text)
        if actions:
            execute_actions(actions, approve_steps=approve_steps)
        else:
            log.warning("No valid actions extracted from the LLM response.")
            
    except Exception as e:
        import traceback
        log.error(f"Failed to communicate with Azure OpenAI: {e}\n{traceback.format_exc()}")


def _parse_cli_arguments(arguments: list[str]) -> tuple[list[str], bool]:
    confirm_steps = "--confirm-steps" in arguments
    query_arguments = [
        argument
        for argument in arguments
        if argument not in {"--approve-steps", "--confirm-steps"}
    ]
    return query_arguments, not confirm_steps

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    os.environ.setdefault(
        "YANTRA_AUDIT_LOG_PATH",
        os.path.join(
            os.path.expanduser("~"),
            ".local",
            "state",
            "yantra",
            "audit.jsonl",
        ),
    )
    
    arguments = sys.argv[1:]
    arguments, approve_steps = _parse_cli_arguments(arguments)
    if not arguments:
        print("Usage: python yantra_core.py [--confirm-steps] <natural language query>")
        sys.exit(1)

    query = " ".join(arguments)
    process_query(query, approve_steps=approve_steps)
