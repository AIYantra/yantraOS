import os
import sys
import logging
from dotenv import load_dotenv

# Ensure we can import yantra_core from the core directory
sys.path.append(os.path.join(os.path.dirname(__file__), "core"))
import yantra_core

logging.basicConfig(level=logging.INFO)

def main():
    print("Loading environment from .env...")
    load_dotenv()
    
    if not os.getenv("AZURE_OPENAI_ENDPOINT"):
        print("Error: AZURE_OPENAI_ENDPOINT is not set. Please copy .env.example to .env and fill in the details.")
        sys.exit(1)
        
    query = "Navigate to https://en.wikipedia.org/wiki/Main_Page. Take a screenshot, read the exact title of 'Today's featured article', and save that exact title to a file at /tmp/extract1.txt."
    print(f"Testing Yantra Core with query: '{query}'")
    
    yantra_core.process_query(query)

if __name__ == "__main__":
    main()
