import os
import json
import logging
import chromadb
from chromadb.utils import embedding_functions

log = logging.getLogger(__name__)

CHROMA_PATH = "/shared_data/chroma"
COLLECTION_NAME = "skill_index"

class VectorMemory:
    def __init__(self):
        # Initialize persistent client. If running inside the sandbox/daemon,
        # /shared_data is mapped to the host's BTRFS subvolume.
        os.makedirs(CHROMA_PATH, exist_ok=True)
        self.client = chromadb.PersistentClient(path=CHROMA_PATH)
        
        # Use sentence-transformers for local, privacy-preserving embeddings
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        
        # Get or create the collection
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self.embedding_fn
        )
        log.info(f"VectorMemory initialized at {CHROMA_PATH} for collection '{COLLECTION_NAME}'")

    def upsert_skill(self, skill_data: dict) -> bool:
        """
        Upsert a skill matching the yantraos/skill/v1 schema into ChromaDB.
        Generates vector embeddings for the title + description + tags.
        """
        try:
            skill_id = skill_data.get("id")
            if not skill_id:
                raise ValueError("Skill missing 'id' field")
                
            # Create a rich semantic document string to embed
            title = skill_data.get("title", "")
            desc = skill_data.get("description", "")
            tags = " ".join(skill_data.get("tags", []))
            
            document = f"Title: {title}\nDescription: {desc}\nTags: {tags}"
            
            # Flatten metadata for ChromaDB (must be strings, ints, floats, bools)
            metadata = {
                "title": title,
                "category": skill_data.get("category", "utility"),
                "version": skill_data.get("version", "1.0.0"),
                "author": skill_data.get("author", "unknown"),
                "is_public": skill_data.get("is_public", False)
            }
            
            # Add execution environment specifics to metadata
            env = skill_data.get("execution_environment", {})
            metadata["env_type"] = env.get("type", "hybrid")
            
            # Perform upsert
            self.collection.upsert(
                ids=[skill_id],
                documents=[document],
                metadatas=[metadata]
            )
            log.info(f"Successfully upserted skill '{title}' ({skill_id}) into VectorMemory")
            return True
            
        except Exception as e:
            log.error(f"Failed to upsert skill into VectorMemory: {e}")
            return False

    def query_skills(self, query: str, n_results: int = 3) -> list:
        """Query for semantically related skills."""
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            return results
        except Exception as e:
            log.error(f"VectorMemory query failed: {e}")
            return []

# Singleton instance
_instance = None

def get_memory() -> VectorMemory:
    global _instance
    if _instance is None:
        _instance = VectorMemory()
    return _instance
