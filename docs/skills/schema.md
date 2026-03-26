# yantraos/skill/v1 Schema

The `yantraos/skill/v1` schema defines the fundamental unit of execution, memory, and utility within YantraOS: a **Skill**. Skills represent specialized logic capabilities—from inference integrations and RAG pipelines to system automation routines.

All Skills are stored and resolved semantically in the Pinecone Vector Database.

## JSON Payload Specification

```json
{
  "$schema": "yantraos/skill/v1",
  "id": "string (uuid-v4)",
  "title": "string",
  "description": "string",
  "version": "string (semver, e.g. '1.2.0')",
  "icon_reference": "string (lucide icon name or absolute path to SVG asset)",
  "tags": ["string"],
  "category": "enum: 'automation' | 'inference' | 'rag' | 'data' | 'system' | 'utility'",
  "execution_environment": {
    "type": "enum: 'local' | 'cloud' | 'hybrid'",
    "requires_vram_gb": "number | null",
    "supported_models": ["string (model slug)"],
    "daemon_hook": "string (Kriya Loop daemon endpoint, e.g. '/api/kriya/execute')"
  },
  "pinecone_metadata": {
    "index_name": "string",
    "namespace": "string",
    "vector_dimensions": 1536
  },
  "author": "string",
  "created_at": "ISO 8601 timestamp",
  "updated_at": "ISO 8601 timestamp",
  "is_public": "boolean",
  "download_count": "number"
}
```

## Pinecone Vector Topology

YantraOS uses Pinecone for its declarative **Vector Memory**. When a Skill is installed or acquired through One-Shot Learning, its semantic meaning is embedded and offloaded into Pinecone.

### The 1536-Dimensional Embedding Requirement

Every Skill payload inserted into Pinecone must be embedded as a strictly **1536-dimensional vector**. This invariant matches the embedding signature of `text-embedding-3-small`.

Failure to match this dimensionality (e.g., using a 768-dim model) will result in a fatal `DimensionMismatchError` during upsertion, rejecting the Skill from the `yantra-skills` global index.

### Index and Namespace Strategy

The core system index is defined as:

| Name | Dimensions | Metric | Strategy |
| :--- | :--- | :--- | :--- |
| `yantra-skills` | 1536 | Cosine | One unique namespace per Skill Slug |

When the Kriya Loop needs to formulate a reasoning plan, it performs a $K$-Nearest Neighbor (KNN) cosine similarity search against this index. The returned metadata (the Skill ID, tags, title, version) dynamically dictates the tools the AI OS has at its immediate disposal without flooding its context window.
