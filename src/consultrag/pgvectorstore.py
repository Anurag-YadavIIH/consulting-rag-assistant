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


class PgVectorStore:
    def __init__(self, dim: int, dsn: str | None = None, table_name: str = "chunks"):
        import psycopg
        from pgvector.psycopg import register_vector

        from .config import settings

        self.dim = dim
        self.table_name = _validate_table_name(table_name)
        self._conn = psycopg.connect(dsn or settings.database_url, autocommit=False)
        register_vector(self._conn)
        ensure_schema(self._conn, dim, self.table_name)

    def __len__(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {self.table_name}")
            return cur.fetchone()[0]

    def all_chunks(self):
        from .vectorstore import StoredChunk

        with self._conn.cursor() as cur:
            cur.execute(f"SELECT chunk_id, text, metadata FROM {self.table_name}")
            return [StoredChunk(chunk_id=r[0], text=r[1], metadata=r[2]) for r in cur.fetchall()]

    def add(self, vectors, chunks) -> None:
        if vectors.shape[0] != len(chunks):
            raise ValueError("vectors and chunks length mismatch")
        if vectors.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {vectors.shape[1]}")
        from psycopg.types.json import Jsonb

        with self._conn.cursor() as cur:
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
                    {
                        "chunk_id": chunk.chunk_id,
                        "text": chunk.text,
                        "embedding": vec,
                        "engagement": chunk.metadata.get("engagement"),
                        "clearance": int(chunk.metadata.get("clearance", 1)),
                        "metadata": Jsonb(chunk.metadata),
                    },
                )
        self._conn.commit()

    def search(self, query_vec, top_k: int = 5, user: User | None = None) -> list[dict]:
        where = ["TRUE"]
        params: dict = {"qvec": query_vec, "top_k": top_k}
        if user is not None:
            where.append("clearance <= %(clearance)s")
            params["clearance"] = user.clearance
            if not AccessPolicy.is_admin(user):
                where.append("(engagement IS NULL OR engagement = ANY(%(engagements)s))")
                params["engagements"] = AccessPolicy.engagements_for(user)

        sql = f"""
            SELECT chunk_id, text, metadata, 1 - (embedding <=> %(qvec)s) AS score
            FROM {self.table_name}
            WHERE {' AND '.join(where)}
            ORDER BY embedding <=> %(qvec)s
            LIMIT %(top_k)s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [
            {"chunk_id": r[0], "text": r[1], "metadata": r[2], "score": float(r[3])}
            for r in rows
        ]

    def save(self, directory: str | Path | None = None) -> None:
        # Every add() already commits to Postgres — nothing to flush to disk.
        # Kept for interface parity with NumpyVectorStore.save().
        pass

    @classmethod
    def load(cls, dim: int, dsn: str | None = None, table_name: str = "chunks") -> "PgVectorStore":
        return cls(dim=dim, dsn=dsn, table_name=table_name)
