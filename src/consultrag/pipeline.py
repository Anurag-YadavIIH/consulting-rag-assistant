"""
Ingestion pipeline: file(s) -> sections -> REDACT -> chunks -> embed -> store.

Redaction happens before chunking/embedding so nothing sensitive is ever
vectorized or persisted. The audit log records what was redacted and how many
chunks were produced.
"""

from __future__ import annotations

from pathlib import Path

from .audit import AuditLog
from .chunking import Chunker
from .embeddings import Embedder
from .ingestion.registry import LoaderRegistry
from .security.redaction import Redactor
from .vectorstore import NumpyVectorStore, StoredChunk


class IngestionPipeline:
    def __init__(
        self,
        embedder: Embedder,
        store: NumpyVectorStore,
        redactor: Redactor | None = None,
        chunker: Chunker | None = None,
        audit: AuditLog | None = None,
        default_metadata: dict | None = None,
    ):
        self.embedder = embedder
        self.store = store
        self.redactor = redactor or Redactor()
        self.chunker = chunker or Chunker()
        self.registry = LoaderRegistry()
        self.audit = audit
        self.default_metadata = default_metadata or {}

    def ingest_path(self, path: str | Path, *,
                    engagement: str | None = None,
                    clearance: int = 1,
                    user_id: str = "system") -> int:
        path = Path(path)
        sections = (
            self.registry.load_directory(path)
            if path.is_dir()
            else self.registry.load(path)
        )

        # Redact every section first.
        total_redactions: dict[str, int] = {}
        for s in sections:
            s.text, report = self.redactor.redact(s.text)
            for k, v in report.counts.items():
                total_redactions[k] = total_redactions.get(k, 0) + v

        # Chunk.
        chunks = self.chunker.chunk_sections(sections)
        if not chunks:
            return 0

        # Attach access-control + caller metadata.
        for c in chunks:
            c.metadata.update(self.default_metadata)
            if engagement:
                c.metadata["engagement"] = engagement
            c.metadata["clearance"] = clearance

        # Embed + store.
        vectors = self.embedder.embed([c.text for c in chunks])
        stored = [
            StoredChunk(chunk_id=c.chunk_id, text=c.text, metadata=c.metadata)
            for c in chunks
        ]
        self.store.add(vectors, stored)

        if self.audit:
            self.audit.log_ingest(
                source_path=path.as_posix(),
                n_chunks=len(chunks),
                redaction_counts=total_redactions,
                user_id=user_id,
            )
        return len(chunks)
