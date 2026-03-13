"""
YantraOS — ChromaDB Persistent Vector Memory
Target: /opt/yantra/core/vector_memory.py
Milestone 2, Task 2.3

Provides the persistent memory layer for the Kriya Loop's one-shot skill
acquisition system (YANTRA_MASTER_CONTEXT §4.9). Each successful execution
path is embedded and stored so the daemon can retrieve verified solutions
before generating new code.

Storage backend: ChromaDB PersistentClient at /var/lib/yantra/chromadb
  - Ownership: yantra_daemon:yantra (set by systemd-tmpfiles in Milestone 1)
  - BTRFS +C (nodatacow) attribute applied to the directory — no chown
    or chattr operations are required or performed in this module.

Non-blocking I/O strategy:
  - All ChromaDB write operations (add, upsert) are dispatched via
    asyncio.get_event_loop().run_in_executor(None, ...) to prevent the
    synchronous ChromaDB client from stalling the async Kriya Loop.
  - Read operations (query) follow the same pattern for consistency.
  - The executor uses Python's default ThreadPoolExecutor, which is
    appropriate for I/O-bound ChromaDB calls. Do NOT use ProcessPoolExecutor —
    the ChromaDB client is not fork-safe.

Collections:
  • "execution_logs"  — Action outcomes from the ACT phase (skill acquisition)
  • "skill_index"     — Installed Skill package metadata for semantic search
  • "error_patterns"  — Known error signatures for pattern-matched remediation
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from typing import Any

log = logging.getLogger("yantra.vector_memory")

# ── Constants ─────────────────────────────────────────────────────────────────

CHROMA_PATH: str = "/var/lib/yantra/chromadb"

# Collection names — changing these after first boot requires a migration.
COLLECTION_EXECUTION_LOGS: str = "execution_logs"
COLLECTION_SKILL_INDEX: str = "skill_index"
COLLECTION_ERROR_PATTERNS: str = "error_patterns"

# Semantic similarity threshold for retrieval.
# Cosine distance ≤ 0.35 is treated as a high-confidence match.
SIMILARITY_THRESHOLD: float = 0.35

# Maximum results returned from a single query.
QUERY_TOP_K: int = 5

# ── Record Types ──────────────────────────────────────────────────────────────


@dataclass
class ExecutionRecord:
    """
    A single action outcome stored after the ACT phase completes.
    The `document` field is what gets embedded by ChromaDB's default
    embedding function (sentence-transformers/all-MiniLM-L6-v2).
    """
    action_type: str                     # e.g., "cleanup", "package_install"
    outcome: str                         # "success" | "failure" | "partial"
    command_sequence: list[str]          # Ordered list of commands executed
    iterations: int                      # Kriya Loop iteration number
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    def to_document(self) -> str:
        """Serialize to a natural-language string for embedding."""
        cmds = " → ".join(self.command_sequence) if self.command_sequence else "none"
        return (
            f"Action: {self.action_type}. "
            f"Outcome: {self.outcome}. "
            f"Commands: {cmds}. "
            f"Tags: {', '.join(self.tags)}."
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "outcome": self.outcome,
            "iterations": self.iterations,
            "timestamp": self.timestamp,
            "tags": json.dumps(self.tags),
        }

    def record_id(self) -> str:
        """Deterministic ID derived from content hash — deduplicates retries."""
        content = f"{self.action_type}:{':'.join(self.command_sequence)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class MemoryQueryResult:
    """Result of a semantic similarity query."""
    document: str
    metadata: dict[str, Any]
    distance: float
    id: str

    @property
    def is_high_confidence(self) -> bool:
        return self.distance <= SIMILARITY_THRESHOLD


# ── VectorMemory ──────────────────────────────────────────────────────────────


class VectorMemory:
    """
    Async-safe ChromaDB interface for the Kriya Loop.

    All blocking ChromaDB calls are offloaded to a dedicated single-thread
    executor to ensure daemon latency stays within the 10 s iteration budget.

    Initialization is lazy — the ChromaDB client is not created until the
    first call to `initialize()`. Import does not trigger disk I/O.
    """

    def __init__(self, path: str = CHROMA_PATH) -> None:
        self._path = path
        self._client: Any = None                  # chromadb.PersistentClient
        self._exec_logs: Any = None               # ChromaDB Collection
        self._skill_index: Any = None             # ChromaDB Collection
        self._error_patterns: Any = None          # ChromaDB Collection
        # Single-thread executor: ChromaDB SQLite backend is not thread-safe
        # beyond sequential access. One thread serializes all I/O.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="yantra-chroma"
        )
        self._initialized: bool = False
        self._init_failed: bool = False  # True if init was attempted and failed

    async def initialize(self) -> None:
        """
        Create the ChromaDB PersistentClient and ensure all collections exist.

        Called once by the Kriya Loop engine after startup, before the first
        REMEMBER phase. Idempotent — safe to call on restart.
        """
        if self._initialized:
            return
        if self._init_failed:
            return  # Already tried and failed — don't retry every cycle

        log.info(f"> MEMORY: Initializing ChromaDB at {self._path}")

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._executor, self._blocking_init)
            self._initialized = True
            log.info("> MEMORY: ChromaDB initialized. Collections ready.")
        except Exception as exc:
            self._init_failed = True
            log.warning(
                f"> MEMORY: ChromaDB initialization failed — memory subsystem DEGRADED. "
                f"Reason: {exc}. Storage calls will be silently skipped."
            )

    def _blocking_init(self) -> None:
        """Blocking ChromaDB initialization — runs in the dedicated executor."""
        try:
            import chromadb  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "chromadb is not installed. Run: pip install chromadb"
            ) from exc

        # PersistentClient writes to /var/lib/yantra/chromadb.
        # Directory ownership (yantra_daemon:yantra) was set by systemd-tmpfiles.
        # The +C (nodatacow) attribute was applied in Milestone 1 — no chattr here.
        self._client = chromadb.PersistentClient(path=self._path)

        # get_or_create_collection is idempotent — safe on restart.
        self._exec_logs = self._client.get_or_create_collection(
            name=COLLECTION_EXECUTION_LOGS,
            metadata={"hnsw:space": "cosine"},
        )
        self._skill_index = self._client.get_or_create_collection(
            name=COLLECTION_SKILL_INDEX,
            metadata={"hnsw:space": "cosine"},
        )
        self._error_patterns = self._client.get_or_create_collection(
            name=COLLECTION_ERROR_PATTERNS,
            metadata={"hnsw:space": "cosine"},
        )

        log.info(
            f"> MEMORY: Collections — exec_logs: {self._exec_logs.count()}, "
            f"skill_index: {self._skill_index.count()}, "
            f"error_patterns: {self._error_patterns.count()} records"
        )

    async def _require_initialized(self) -> None:
        """Ensure ChromaDB is ready. If init failed, raise to skip the operation."""
        if self._initialized:
            return
        if self._init_failed:
            raise RuntimeError("VectorMemory is DEGRADED — ChromaDB init failed on startup.")
        await self.initialize()
        if not self._initialized:
            raise RuntimeError("VectorMemory is DEGRADED — ChromaDB init failed on startup.")

    # ── Write Operations ──────────────────────────────────────────────────────

    async def store_execution(self, record: ExecutionRecord) -> str:
        """
        Persist an action outcome to the execution_logs collection.

        Non-blocking: the ChromaDB upsert runs in the dedicated executor.
        Returns the record ID for confirmation.
        """
        await self._require_initialized()
        loop = asyncio.get_event_loop()

        record_id = record.record_id()
        document = record.to_document()
        metadata = record.to_metadata()

        # Use upsert — retrying the same command sequence yields the same ID,
        # which overwrites the previous record rather than duplicating it.
        fn = partial(
            self._exec_logs.upsert,
            ids=[record_id],
            documents=[document],
            metadatas=[metadata],
        )
        await loop.run_in_executor(self._executor, fn)

        log.debug(
            f"> MEMORY: Stored execution record [{record_id}] — "
            f"{record.action_type}/{record.outcome}"
        )
        return record_id

    async def store_error_pattern(
        self,
        error_signature: str,
        remediation: str,
        *,
        tags: list[str] | None = None,
    ) -> str:
        """
        Store a known error pattern and its verified remediation sequence.
        Used by the PATCH phase to persist cloud-sourced skill resolutions.
        """
        await self._require_initialized()
        loop = asyncio.get_event_loop()

        record_id = hashlib.sha256(error_signature.encode()).hexdigest()[:16]
        document = f"Error: {error_signature}. Remediation: {remediation}."
        metadata: dict[str, Any] = {
            "error_signature": error_signature,
            "remediation": remediation,
            "tags": json.dumps(tags or []),
            "timestamp": time.time(),
        }

        fn = partial(
            self._error_patterns.upsert,
            ids=[record_id],
            documents=[document],
            metadatas=[metadata],
        )
        await loop.run_in_executor(self._executor, fn)
        log.debug(f"> MEMORY: Stored error pattern [{record_id}]")
        return record_id

    async def index_skill(self, skill_id: str, skill_data: dict[str, Any]) -> None:
        """
        Index a Skill package into the skill_index collection for semantic search.

        skill_data should conform to the yantraos/skill/v1 schema (§3.1).
        The document embedding is derived from title + description + tags.
        """
        await self._require_initialized()
        loop = asyncio.get_event_loop()

        title = skill_data.get("title", "")
        description = skill_data.get("description", "")
        tags = skill_data.get("tags", [])
        document = f"{title}. {description}. Tags: {', '.join(tags)}."
        metadata = {
            "skill_id": skill_id,
            "title": title,
            "category": skill_data.get("category", ""),
            "version": skill_data.get("version", "0.0.0"),
            "tags": json.dumps(tags),
        }

        fn = partial(
            self._skill_index.upsert,
            ids=[skill_id],
            documents=[document],
            metadatas=[metadata],
        )
        await loop.run_in_executor(self._executor, fn)
        log.info(f"> MEMORY: Indexed skill '{title}' [{skill_id}]")

    # ── Read Operations ───────────────────────────────────────────────────────

    async def query_executions(
        self,
        query_text: str,
        *,
        top_k: int = QUERY_TOP_K,
        outcome_filter: str | None = None,
    ) -> list[MemoryQueryResult]:
        """
        Semantic similarity search over past execution logs.

        If outcome_filter is set (e.g., "success"), only records with that
        outcome are returned — useful for retrieving only verified solutions.

        Non-blocking: query runs in the dedicated executor.
        """
        await self._require_initialized()
        loop = asyncio.get_event_loop()

        where: dict[str, Any] | None = None
        if outcome_filter:
            where = {"outcome": {"$eq": outcome_filter}}

        fn = partial(
            self._exec_logs.query,
            query_texts=[query_text],
            n_results=min(top_k, max(self._exec_logs.count(), 1)),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        try:
            results = await loop.run_in_executor(self._executor, fn)
        except Exception as exc:
            log.warning(f"> MEMORY: Execution query failed: {exc}")
            return []

        return _parse_query_results(results)

    async def query_error_patterns(
        self,
        error_description: str,
        *,
        top_k: int = 3,
    ) -> list[MemoryQueryResult]:
        """
        Semantic search for a known remediation matching the described error.
        The PATCH phase calls this before escalating to the cloud skill API.
        """
        await self._require_initialized()
        loop = asyncio.get_event_loop()

        fn = partial(
            self._error_patterns.query,
            query_texts=[error_description],
            n_results=min(top_k, max(self._error_patterns.count(), 1)),
            include=["documents", "metadatas", "distances"],
        )

        try:
            results = await loop.run_in_executor(self._executor, fn)
        except Exception as exc:
            log.warning(f"> MEMORY: Error pattern query failed: {exc}")
            return []

        return _parse_query_results(results)

    async def query_skills(
        self,
        query_text: str,
        *,
        top_k: int = QUERY_TOP_K,
        category_filter: str | None = None,
    ) -> list[MemoryQueryResult]:
        """
        Semantic search over the installed skill index.
        Called by the Skill Acquisition pipeline before cloud lookup.
        """
        await self._require_initialized()
        loop = asyncio.get_event_loop()

        where: dict[str, Any] | None = None
        if category_filter:
            where = {"category": {"$eq": category_filter}}

        fn = partial(
            self._skill_index.query,
            query_texts=[query_text],
            n_results=min(top_k, max(self._skill_index.count(), 1)),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        try:
            results = await loop.run_in_executor(self._executor, fn)
        except Exception as exc:
            log.warning(f"> MEMORY: Skill query failed: {exc}")
            return []

        return _parse_query_results(results)

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, int]:
        """Return record counts for all collections."""
        if not self._initialized:
            return {}
        loop = asyncio.get_event_loop()

        def _counts() -> dict[str, int]:
            return {
                COLLECTION_EXECUTION_LOGS: self._exec_logs.count(),
                COLLECTION_SKILL_INDEX: self._skill_index.count(),
                COLLECTION_ERROR_PATTERNS: self._error_patterns.count(),
            }

        return await loop.run_in_executor(self._executor, _counts)

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """
        Gracefully shut down the executor. Call this from the daemon's
        shutdown handler to ensure in-flight writes are completed before exit.
        """
        log.info("> MEMORY: Shutting down vector memory executor...")
        self._executor.shutdown(wait=True)
        log.info("> MEMORY: Executor shut down. All writes flushed.")


# ── Module-level singleton ────────────────────────────────────────────────────

# The Kriya Loop engine imports this singleton and calls await memory.initialize()
# once during startup. Subsequent phases (REMEMBER, PATCH) use it directly.
memory = VectorMemory(path=CHROMA_PATH)

# ── Result Parser ─────────────────────────────────────────────────────────────


def _parse_query_results(raw: dict[str, Any]) -> list[MemoryQueryResult]:
    """Convert ChromaDB query response format into typed MemoryQueryResult objects."""
    results: list[MemoryQueryResult] = []

    try:
        ids_list = raw.get("ids", [[]])[0]
        docs_list = raw.get("documents", [[]])[0]
        meta_list = raw.get("metadatas", [[]])[0]
        dist_list = raw.get("distances", [[]])[0]

        for record_id, doc, meta, dist in zip(ids_list, docs_list, meta_list, dist_list):
            results.append(MemoryQueryResult(
                id=record_id,
                document=doc,
                metadata=meta or {},
                distance=float(dist),
            ))
    except (IndexError, TypeError, KeyError) as exc:
        log.warning(f"> MEMORY: Failed to parse query results: {exc}")

    return results
