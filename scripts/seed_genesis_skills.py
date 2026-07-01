import sys
import uuid
import datetime

# Add parent directory to path so we can import core modules
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.vector_memory import get_memory

def seed_genesis_skills():
    print("Initialize VectorMemory...")
    memory = get_memory()
    
    # Define the skill payload matching the yantraos/skill/v1 specification
    skill_payload = {
        "$schema": "yantraos/skill/v1",
        "id": str(uuid.uuid4()),
        "title": "Automated Dependency Healer",
        "description": "Recognize package degradation events and heal them completely inside the Docker sandbox. SANDBOX POLICY: Mount read-only token contract pointing to host virtual environment verification paths.",
        "version": "1.0.0",
        "icon_reference": "terminal",
        "tags": ["python", "venv", "automation", "devops", "healing", "sandbox-policy:readonly-token-contract"],
        "category": "system",
        "execution_environment": {
            "type": "hybrid",
            "requires_vram_gb": 0,
            "supported_models": ["gpt-4o-mini", "gpt-5.4-mini", "deepseek-v4"],
            "daemon_hook": "/api/kriya/execute"
        },
        "pinecone_metadata": {
            "index_name": "yantra-memory",
            "namespace": "skills",
            "vector_dimensions": 1536
        },
        "author": "YantraOS Genesis",
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": datetime.datetime.now().isoformat(),
        "is_public": True,
        "download_count": 0
    }
    
    print(f"Upserting skill '{skill_payload['title']}'...")
    success = memory.upsert_skill(skill_payload)
    
    if success:
        print("✅ Genesis skill successfully provisioned into ChromaDB.")
        
        # Verify it can be queried
        print("Running verification query...")
        results = memory.query_skills("dependency conflict python")
        if results and results.get("ids") and len(results["ids"][0]) > 0:
            print(f"✅ Query successful. Found: {results['metadatas'][0][0]['title']}")
        else:
            print("❌ Query returned no results.")
    else:
        print("❌ Failed to upsert genesis skill.")
        sys.exit(1)

if __name__ == "__main__":
    seed_genesis_skills()
