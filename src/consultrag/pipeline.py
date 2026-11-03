"""
Ingestion pipeline: file(s) -> sections -> REDACT -> chunks -> embed -> store.

Redaction happens before chunking/embedding so nothing sensitive is ever
vectorized or persisted. The audit log records what was redacted and how many
chunks were produced.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .audit import AuditLog
from .chunking import Chunker
from .embeddings import Embedder
from .ingestion.registry import LoaderRegistry
from .security.redaction import Redactor
from .vectorstore import NumpyVectorStore, StoredChunk

# Prefix for chunk IDs of named (uploaded) documents. RawSection normalizes
# every loader path with Path.as_posix(), which collapses "//", so no ID built
# from a filesystem path can ever start with this.
UPLOAD_ID_PREFIX = "upload://"


class DocumentLoadError(ValueError):
    """A file could not be parsed by its loader (corrupt, wrong format, or an
    unsupported extension). Subclasses ValueError, which load() raised before."""


class DocumentTooLarge(ValueError):
    """The document's extracted text would make more chunks than allowed.
    Raised before anything is embedded or stored."""

    def __init__(self, n_chunks: int, max_chunks: int):
        super().__init__(f"{n_chunks} chunks exceeds the limit of {max_chunks}")
        self.n_chunks = n_chunks
        self.max_chunks = max_chunks


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
                    user_id: str = "system",
                    source_name: str | None = None,
                    replace_max_clearance: int | None = None,
                    max_chunks: int | None = None) -> int:
        """Ingest a file or directory.

        With `source_name` (used by uploads), `path` is a single temporary
        file and `source_name` is the document's name: it replaces the
        temporary path in citations, chunk IDs and the audit log, and the
        document REPLACES any existing document of that name in `engagement`
        atomically (see the store's replace_document). Existing chunks above
        `replace_max_clearance` block the replacement with
        DocumentReplaceForbidden; None means no limit (admins).

        `max_chunks` caps the extracted text: a document that would make more
        chunks raises DocumentTooLarge after loading, redaction and chunking
        but BEFORE embedding, so it costs no embedding time and leaves any
        existing document untouched. None means no limit."""
        path = Path(path)
        if source_name is not None and not engagement:
            raise ValueError("source_name requires an engagement")
        try:
            sections = (
                self.registry.load_directory(path)
                if path.is_dir()
                else self.registry.load(path)
            )
        except Exception as e:
            raise DocumentLoadError(str(e)) from e
        if source_name is not None:
            # Set after RawSection.__post_init__, so the name is kept verbatim.
            for s in sections:
                s.source_path = source_name

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
        if max_chunks is not None and len(chunks) > max_chunks:
            raise DocumentTooLarge(len(chunks), max_chunks)

        # Attach access-control + caller metadata. ingested_at (UTC, ISO 8601)
        # is what GET /documents reports as the upload time.
        ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for c in chunks:
            c.metadata.update(self.default_metadata)
            c.metadata["ingested_at"] = ingested_at
            if engagement:
                c.metadata["engagement"] = engagement
            c.metadata["clearance"] = clearance
            if source_name is not None:
                # Namespaced by engagement: the same filename uploaded to two
                # engagements must never share (and so overwrite) a chunk ID.
                c.chunk_id = f"{UPLOAD_ID_PREFIX}{engagement}/{c.chunk_id}"

        # Embed + store.
        vectors = self.embedder.embed([c.text for c in chunks])
        stored = [
            StoredChunk(chunk_id=c.chunk_id, text=c.text, metadata=c.metadata)
            for c in chunks
        ]
        document = source_name if source_name is not None else path.as_posix()
        # A transactional audit log (PgAuditLog) is written by the store inside
        # the same transaction as the change, so a failed audit write rolls
        # the ingest back. Otherwise (the CLI's file log) it's written after.
        audit_event = None
        if self.audit is not None and getattr(self.audit, "transactional", False):
            audit_event = self.audit.ingest_event(
                user_id=user_id, engagement=engagement, document=document,
                n_chunks=len(chunks), redaction_counts=total_redactions,
            )
        if source_name is not None:
            self.store.replace_document(
                engagement, source_name, vectors, stored,
                max_existing_clearance=replace_max_clearance,
                audit_event=audit_event,
            )
        else:
            self.store.add(vectors, stored, audit_event=audit_event)

        if self.audit is not None and audit_event is None:
            self.audit.log_ingest(
                source_path=document,
                n_chunks=len(chunks),
                redaction_counts=total_redactions,
                user_id=user_id,
                engagement=engagement,
            )
        return len(chunks)

    def delete_document(self, engagement: str, name: str, *, user_id: str,
                        max_existing_clearance: int | None = None) -> int:
        """Deletes one named document from an engagement; returns the number
        of chunks removed (0 if there was no such document). Raises
        DocumentReplaceForbidden if any chunk is above
        `max_existing_clearance` (the same rule as replacing it). The audit
        event shares the delete's transaction when the log is transactional."""
        transactional = self.audit is not None and getattr(self.audit, "transactional", False)
        factory = None
        if transactional:
            def factory(n_chunks: int) -> dict:
                return self.audit.delete_event(
                    user_id=user_id, engagement=engagement, document=name, n_chunks=n_chunks
                )
        n = self.store.delete_document(
            engagement, name, max_existing_clearance=max_existing_clearance,
            audit_event_factory=factory,
        )
        if n and self.audit is not None and not transactional:
            self.audit.log_delete(source_path=name, n_chunks=n, user_id=user_id,
                                  engagement=engagement)
        return n
