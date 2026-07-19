import subprocess
import json
import sys

def run_bridge(intent: dict) -> None:
    intent_str = json.dumps(intent)
    print(f"\n--- Testing Intent: {intent['action']} ---")
    cmd = [
        sys.executable,
        "core/foundry_action_bridge.py",
    ]
    try:
        result = subprocess.run(cmd, input=intent_str, check=True, text=True)
        print(f"--- Execution Successful ---\n")
    except subprocess.CalledProcessError as e:
        print(f"--- Execution Failed with exit code {e.returncode} ---\n")

def main():
    # 1. Create a file
    create_file_intent = {
        "action": "create_dummy_file",
        "path": "/tmp/dummy_test_file.txt",
        "content": "Hello from the local action bridge!"
    }
    
    # 2. Open URL
    open_url_intent = {
        "action": "open_url",
        "url": "https://yantraos.com"
    }

    run_bridge(create_file_intent)
    run_bridge(open_url_intent)

if __name__ == "__main__":
    main()
