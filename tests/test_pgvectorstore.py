"""
PgVectorStore tests against a real Postgres+pgvector instance. Skip cleanly
(not fail) if psycopg isn't installed or Postgres isn't reachable, so
`pytest tests/ -q` stays green offline — run `docker compose up -d` first to
actually exercise this file.

Uses an isolated table (never the default 'chunks' table) so it can't
collide with or corrupt real ingested data, and drops that table afterward.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.config import settings
from consultrag.security.access import User
from consultrag.vectorstore import StoredChunk

TEST_TABLE = "chunks_test_consultrag"


def _pg_available() -> bool:
    try:
        import psycopg
    except ImportError:
        return False
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="Postgres not reachable")


@pytest.fixture
def store():
    from consultrag.pgvectorstore import PgVectorStore

    s = PgVectorStore(dim=4, table_name=TEST_TABLE)
    yield s
    with s._conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {TEST_TABLE}")
    s._conn.commit()
    s._conn.close()


def _chunk(cid, text, engagement, clearance):
    return StoredChunk(
        chunk_id=cid, text=text,
        metadata={"engagement": engagement, "clearance": clearance, "source_path": "x"},
    )


def test_add_and_search_round_trip(store):
    vectors = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
    chunks = [
        _chunk("a", "alpha content", "acme", 1),
        _chunk("b", "beta content", "acme", 1),
    ]
    store.add(vectors, chunks)
    assert len(store) == 2

    qvec = np.array([1, 0, 0, 0], dtype=np.float32)
    results = store.search(qvec, top_k=2)
    assert results[0]["chunk_id"] == "a"
    assert results[0]["score"] > results[1]["score"]


def test_all_chunks_returns_everything(store):
    vectors = np.array([[1, 0, 0, 0]], dtype=np.float32)
    store.add(vectors, [_chunk("a", "alpha", "acme", 1)])
    chunks = store.all_chunks()
    assert [c.chunk_id for c in chunks] == ["a"]


def test_sql_filter_blocks_other_engagement_before_access_policy(store):
    # Defense-in-depth: prove the SQL filter itself excludes blocked rows,
    # independent of AccessPolicy.filter() (which never runs in this test).
    vectors = np.array([[1, 0, 0, 0], [0.9, 0.1, 0, 0]], dtype=np.float32)
    store.add(vectors, [
        _chunk("acme-doc", "acme content", "acme", 1),
        _chunk("globex-doc", "globex content", "globex", 1),
    ])
    user = User.make("u", roles=["analyst", "engagement:acme"], clearance=5)
    qvec = np.array([1, 0, 0, 0], dtype=np.float32)
    results = store.search(qvec, top_k=5, user=user)
    assert [r["chunk_id"] for r in results] == ["acme-doc"]


def test_sql_filter_blocks_insufficient_clearance(store):
    vectors = np.array([[1, 0, 0, 0]], dtype=np.float32)
    store.add(vectors, [_chunk("secret-doc", "content", None, 3)])
    low_clearance_user = User.make("u", roles=["analyst"], clearance=1)
    qvec = np.array([1, 0, 0, 0], dtype=np.float32)
    assert store.search(qvec, top_k=5, user=low_clearance_user) == []


def test_admin_bypasses_engagement_filter(store):
    vectors = np.array([[1, 0, 0, 0]], dtype=np.float32)
    store.add(vectors, [_chunk("globex-doc", "content", "globex", 1)])
    admin = User.make("u", roles=["admin"], clearance=5)
    qvec = np.array([1, 0, 0, 0], dtype=np.float32)
    results = store.search(qvec, top_k=5, user=admin)
    assert [r["chunk_id"] for r in results] == ["globex-doc"]
