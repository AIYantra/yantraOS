"""
YantraOS — Vector Memory (Lightweight Embedding Engine)
Target: /opt/yantra/core/vector_memory.py

Manages the local ChromaDB skill registry. Embedding generation is
offloaded to Ollama (local) or Azure OpenAI (cloud fallback).
No PyTorch. No transformers. The daemon stays lean.
"""

import os
import logging
import httpx
import chromadb

log = logging.getLogger(__name__)

CHROMA_PATH = "/shared_data/chroma"
COLLECTION_NAME = "skill_index"

# Ollama embedding config
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Azure OpenAI embedding fallback config
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2026-03-17")
AZURE_EMBED_DEPLOYMENT = os.getenv("AZURE_EMBED_DEPLOYMENT", "text-embedding-3-small")

# Timeout for embedding HTTP calls (seconds) — prevents Kriya Loop stalls
EMBED_TIMEOUT = 15.0


class OllamaEmbeddingFunction:
    """
    ChromaDB-compatible embedding function that routes to Ollama first,
    then falls back to Azure OpenAI if the local inference server is offline.
    All calls are synchronous httpx (ChromaDB's interface is sync).
    Timeouts are strictly bounded to prevent event loop starvation.
    """

    def name(self) -> str:
        """Required by ChromaDB >= 1.5 embedding function contract."""
        return "ollama_azure_hybrid"

    @staticmethod
    def build_from_config(config: dict) -> "OllamaEmbeddingFunction":
        """Required by ChromaDB >= 1.5 embedding function contract."""
        return OllamaEmbeddingFunction()

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        # --- PRIMARY: Ollama local path ---
        try:
            embeddings = self._embed_via_ollama(input)
            if embeddings:
                return embeddings
        except Exception as e:
            log.warning(f"VECTOR: Ollama embedding failed ({e}), attempting Azure fallback")

        # --- FALLBACK: Azure OpenAI cloud path ---
        try:
            embeddings = self._embed_via_azure(input)
            if embeddings:
                return embeddings
        except Exception as e:
            log.warning(f"VECTOR: Azure embedding fallback failed ({e}), using zero vectors")

        # --- LAST RESORT: Return zero vectors so ChromaDB doesn't crash ---
        log.error("VECTOR: All embedding backends offline. Returning zero vectors.")
        return [[0.0] * 384 for _ in input]

    def _embed_via_ollama(self, texts: list[str]) -> list[list[float]] | None:
        """Call Ollama POST /api/embed for batch embedding."""
        url = f"{OLLAMA_BASE}/api/embed"
        payload = {
            "model": OLLAMA_EMBED_MODEL,
            "input": texts,
        }
        with httpx.Client(timeout=EMBED_TIMEOUT) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings")
            if embeddings and len(embeddings) == len(texts):
                log.debug(f"VECTOR: Ollama returned {len(embeddings)} embeddings via {OLLAMA_EMBED_MODEL}")
                return embeddings
            return None

    def _embed_via_azure(self, texts: list[str]) -> list[list[float]] | None:
        """Call Azure OpenAI embeddings API as cloud fallback."""
        if not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_API_KEY:
            log.debug("VECTOR: Azure embedding credentials not configured, skipping fallback")
            return None

        url = (
            f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/"
            f"{AZURE_EMBED_DEPLOYMENT}/embeddings"
            f"?api-version={AZURE_OPENAI_API_VERSION}"
        )
        headers = {
            "api-key": AZURE_OPENAI_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "input": texts,
        }
        with httpx.Client(timeout=EMBED_TIMEOUT) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            embeddings = [item["embedding"] for item in data.get("data", [])]
            if embeddings and len(embeddings) == len(texts):
                log.debug(f"VECTOR: Azure returned {len(embeddings)} embeddings via {AZURE_EMBED_DEPLOYMENT}")
                return embeddings
            return None


class VectorMemory:
    def __init__(self):
        # Initialize persistent client. If running inside the sandbox/daemon,
        # /shared_data is mapped to the host's BTRFS subvolume.
        os.makedirs(CHROMA_PATH, exist_ok=True)
        self.client = chromadb.PersistentClient(path=CHROMA_PATH)

        # Lightweight embedding function — no PyTorch, no transformers
        self.embedding_fn = OllamaEmbeddingFunction()

        # Get or create the collection
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self.embedding_fn
        )
        log.info(f"VectorMemory initialized at {CHROMA_PATH} for collection '{COLLECTION_NAME}'")

    def upsert_skill(self, skill_data: dict) -> bool:
        """
        Upsert a skill matching the yantraos/skill/v1 schema into ChromaDB.
        Embedding generation is delegated to the OllamaEmbeddingFunction.
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

            # Perform upsert — embedding is generated via Ollama/Azure at call time
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

