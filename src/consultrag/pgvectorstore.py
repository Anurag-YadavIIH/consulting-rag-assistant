"""
Postgres + pgvector vector store — mirrors NumpyVectorStore's interface
(add/search/save/load/all_chunks/__len__) so RAGEngine, HybridRetriever, and
the eval harness work against either backend unchanged.

Engagement and clearance are promoted to indexed columns (denormalized from
`metadata`) so they can be filtered in SQL — a defense-in-depth check that
runs *in addition to*, not instead of, AccessPolicy.filter() in rag.py. The
SQL filter narrows what ever leaves the database; AccessPolicy remains the
authoritative gate before anything reaches the LLM.

Default backend is still NumpyVectorStore (see --store in scripts/); this is
opt-in via --store pgvector, for SQL-level RBAC and corpora too large to keep
in memory.
"""

from __future__ import annotations

import re
from pathlib import Path

from .security.access import AccessPolicy, User

_VALID_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_table_name(table_name: str) -> str:
    # table_name is developer-supplied (a CLI/config value, not end-user
    # input), but DDL can't parameterize identifiers — validate defensively
    # against SQL injection regardless.
    if not _VALID_IDENTIFIER.match(table_name):
        raise ValueError(f"invalid table name: {table_name!r}")
    return table_name


def ensure_schema(conn, dim: int, table_name: str = "chunks") -> None:
    """Idempotent DDL: creates the table (if missing) for the given embedding
    dimension, plus a defense-in-depth filter index and a best-effort ANN
    index. Shared by PgVectorStore and scripts/migrate_pg.py so there's one
    source of truth for the schema."""
    table_name = _validate_table_name(table_name)
    with conn.cursor() as cur:
        # RDS doesn't run docker/init/, so the migration must enable pgvector.
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id BIGSERIAL PRIMARY KEY,
                chunk_id TEXT NOT NULL UNIQUE,
                text TEXT NOT NULL,
                embedding VECTOR({int(dim)}),
                engagement TEXT,
                clearance INT NOT NULL DEFAULT 1,
                metadata JSONB NOT NULL
            )
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_engagement_clearance_idx "
            f"ON {table_name} (engagement, clearance)"
        )
        try:
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {table_name}_embedding_hnsw_idx "
                f"ON {table_name} USING hnsw (embedding vector_cosine_ops)"
            )
        except Exception:
            # Older pgvector (no HNSW support) or dim too large to index —
            # search still works, just without an ANN index. Not fatal.
            conn.rollback()
    conn.commit()


def _row(vec, chunk) -> dict:
    from psycopg.types.json import Jsonb

    return {
        "chunk_id": chunk.chunk_id,
        "text": chunk.text,
        "embedding": vec,
        "engagement": chunk.metadata.get("engagement"),
        "clearance": int(chunk.metadata.get("clearance", 1)),
        "metadata": Jsonb(chunk.metadata),
    }


class PgVectorStore:
    """Every operation borrows a connection from a small pool (psycopg_pool),
    so concurrent requests don't share one transaction, and a connection
    that has dropped is detected (the pool checks it before handing it out)
    and replaced instead of breaking every later request. Connections run in
    autocommit mode: reads never leave a transaction open, and each write
    runs inside an explicit transaction that commits or rolls back as one,
    together with its audit event when one is given."""

    def __init__(self, dim: int, dsn: str | None = None, table_name: str = "chunks",
                 *, min_size: int = 1, max_size: int = 4):
        import psycopg
        from psycopg_pool import ConnectionPool

        from .config import settings

        self.dim = dim
        self.table_name = _validate_table_name(table_name)
        dsn = dsn or settings.database_url

        # Schema first, on a plain connection: the pool's connections register
        # the pgvector type, which requires the extension to exist.
        with psycopg.connect(dsn) as conn:
            ensure_schema(conn, dim, self.table_name)

        self._pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            # application_name makes the pool's connections identifiable in
            # pg_stat_activity (and lets tests kill exactly these).
            kwargs={"autocommit": True, "application_name": f"consultrag-{self.table_name}"},
            configure=self._configure_connection,
            check=ConnectionPool.check_connection,
            name=f"consultrag-{self.table_name}",
            open=True,
        )

    @staticmethod
    def _configure_connection(conn) -> None:
        from pgvector.psycopg import register_vector

        register_vector(conn)

    @property
    def pool(self):
        """Shared with PgAuditLog, so audit writes use the same connections."""
        return self._pool

    def close(self) -> None:
        self._pool.close()

    def __len__(self) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {self.table_name}")
            return cur.fetchone()[0]

    def all_chunks(self):
        from .vectorstore import StoredChunk

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT chunk_id, text, metadata FROM {self.table_name}")
            return [StoredChunk(chunk_id=r[0], text=r[1], metadata=r[2]) for r in cur.fetchall()]

    def _check_vectors(self, vectors, chunks) -> None:
        if vectors.shape[0] != len(chunks):
            raise ValueError("vectors and chunks length mismatch")
        if vectors.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {vectors.shape[1]}")

    def add(self, vectors, chunks, *, audit_event: dict | None = None) -> None:
        from .audit import insert_audit_event

        self._check_vectors(vectors, chunks)
        with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            for vec, chunk in zip(vectors, chunks):
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                        (chunk_id, text, embedding, engagement, clearance, metadata)
                    VALUES (%(chunk_id)s, %(text)s, %(embedding)s, %(engagement)s,
                            %(clearance)s, %(metadata)s)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        text = EXCLUDED.text,
                        embedding = EXCLUDED.embedding,
                        engagement = EXCLUDED.engagement,
                        clearance = EXCLUDED.clearance,
                        metadata = EXCLUDED.metadata
                    """,
                    _row(vec, chunk),
                )
            if audit_event is not None:
                insert_audit_event(cur, audit_event)

    def _lock_document(self, cur, engagement: str, source_path: str) -> None:
        # Transaction-scoped: serializes replace/delete of the same document,
        # including across API processes, and releases at commit/rollback.
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%(key)s, 0))",
            {"key": f"{self.table_name}/{engagement}/{source_path}"},
        )

    _DOC_MATCH = "WHERE engagement = %(engagement)s AND metadata->>'source_path' = %(source_path)s"

    def replace_document(self, engagement: str, source_path: str, vectors, chunks,
                         max_existing_clearance: int | None = None,
                         *, audit_event: dict | None = None) -> None:
        """Swaps every chunk of one document (same engagement and source_path)
        for `chunks` in ONE transaction: the clearance check, the delete of all
        old chunks, the insert and the audit event either all commit or all
        roll back, so a shorter new version leaves no stale chunks and a
        failure (including a failed audit write) leaves the old version
        intact. Raises DocumentReplaceForbidden (and changes nothing) if any
        existing chunk's clearance is above `max_existing_clearance`; None
        means no limit, for admins.

        Plain INSERT (no ON CONFLICT): if a new chunk_id ever clashed with
        another document's row, the whole replacement fails rather than
        silently overwriting that row."""
        from .audit import insert_audit_event
        from .vectorstore import DocumentReplaceForbidden

        self._check_vectors(vectors, chunks)
        doc = {"engagement": engagement, "source_path": source_path}
        with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            self._lock_document(cur, engagement, source_path)
            cur.execute(f"SELECT MAX(clearance) FROM {self.table_name} {self._DOC_MATCH}", doc)
            existing_max = cur.fetchone()[0]
            if (max_existing_clearance is not None and existing_max is not None
                    and existing_max > max_existing_clearance):
                raise DocumentReplaceForbidden()
            cur.execute(f"DELETE FROM {self.table_name} {self._DOC_MATCH}", doc)
            for vec, chunk in zip(vectors, chunks):
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                        (chunk_id, text, embedding, engagement, clearance, metadata)
                    VALUES (%(chunk_id)s, %(text)s, %(embedding)s, %(engagement)s,
                            %(clearance)s, %(metadata)s)
                    """,
                    _row(vec, chunk),
                )
            if audit_event is not None:
                insert_audit_event(cur, audit_event)

    def delete_document(self, engagement: str, source_path: str,
                        max_existing_clearance: int | None = None,
                        *, audit_event_factory=None) -> int:
        """Deletes every chunk of one document in ONE transaction and returns
        how many were deleted (0 if there was no such document). Raises
        DocumentReplaceForbidden, changing nothing, if any chunk's clearance
        is above `max_existing_clearance` (None = no limit, for admins): the
        same rule as replace_document. `audit_event_factory(n_chunks)` builds
        the audit event, written in the same transaction; nothing is
        written when nothing was deleted."""
        from .audit import insert_audit_event
        from .vectorstore import DocumentReplaceForbidden

        doc = {"engagement": engagement, "source_path": source_path}
        with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            self._lock_document(cur, engagement, source_path)
            cur.execute(f"SELECT MAX(clearance) FROM {self.table_name} {self._DOC_MATCH}", doc)
            existing_max = cur.fetchone()[0]
            if existing_max is None:
                return 0
            if max_existing_clearance is not None and existing_max > max_existing_clearance:
                raise DocumentReplaceForbidden()
            cur.execute(f"DELETE FROM {self.table_name} {self._DOC_MATCH}", doc)
            n = cur.rowcount
            if audit_event_factory is not None:
                insert_audit_event(cur, audit_event_factory(n))
            return n

    def list_documents(self, engagement: str, max_clearance: int) -> list[dict]:
        """Documents in one engagement, grouped by name. A document with ANY
        chunk above `max_clearance` is left out entirely (HAVING), so it
        can't show up or affect the counts. `uploaded_at` is the newest
        `ingested_at` in the document's chunks (None for older documents)."""
        sql = f"""
            SELECT metadata->>'source_path' AS name,
                   COUNT(*) AS chunks,
                   MAX(clearance) AS clearance,
                   MAX(metadata->>'ingested_at') AS uploaded_at
            FROM {self.table_name}
            WHERE engagement = %(engagement)s
            GROUP BY metadata->>'source_path'
            HAVING MAX(clearance) <= %(max_clearance)s
            ORDER BY name
        """
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"engagement": engagement, "max_clearance": max_clearance})
            return [
                {"name": r[0], "chunks": r[1], "clearance": r[2], "uploaded_at": r[3]}
                for r in cur.fetchall()
            ]

    def search(
        self, query_vec, top_k: int = 5, user: User | None = None, engagement: str | None = None
    ) -> list[dict]:
        where = ["TRUE"]
        params: dict = {"qvec": query_vec, "top_k": top_k}
        if user is not None:
            where.append("clearance <= %(clearance)s")
            params["clearance"] = user.clearance
            if not AccessPolicy.is_admin(user):
                where.append("(engagement IS NULL OR engagement = ANY(%(engagements)s))")
                params["engagements"] = AccessPolicy.engagements_for(user)
        # A requested scope only ever narrows the access filter above: it is
        # ANDed with it, and it also excludes chunks with no engagement. Being
        # in the SQL (before LIMIT) means other engagements can't crowd the
        # scoped engagement out of the top_k.
        if engagement is not None:
            where.append("engagement = %(scope_engagement)s")
            params["scope_engagement"] = engagement

        sql = f"""
            SELECT chunk_id, text, metadata, 1 - (embedding <=> %(qvec)s) AS score
            FROM {self.table_name}
            WHERE {' AND '.join(where)}
            ORDER BY embedding <=> %(qvec)s
            LIMIT %(top_k)s
        """
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [
            {"chunk_id": r[0], "text": r[1], "metadata": r[2], "score": float(r[3])}
            for r in rows
        ]

    def save(self, directory: str | Path | None = None) -> None:
        # Every write already commits to Postgres; nothing to flush to disk.
        # Kept for interface parity with NumpyVectorStore.save().
        pass

    @classmethod
    def load(cls, dim: int, dsn: str | None = None, table_name: str = "chunks") -> "PgVectorStore":
        return cls(dim=dim, dsn=dsn, table_name=table_name)
