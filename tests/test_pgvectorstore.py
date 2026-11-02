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


# --- replace_document: atomic per-document replacement (uploads) -------------


def _doc_chunk(cid, text, engagement, clearance, source_path):
    return StoredChunk(
        chunk_id=cid, text=text,
        metadata={"engagement": engagement, "clearance": clearance, "source_path": source_path},
    )


def _vecs(n):
    return np.tile(np.array([[1, 0, 0, 0]], dtype=np.float32), (n, 1))


def _rows(store, engagement, source_path):
    return sorted(
        (c.chunk_id, c.text, c.metadata["clearance"]) for c in store.all_chunks()
        if c.metadata.get("engagement") == engagement and c.metadata.get("source_path") == source_path
    )


def test_replace_document_shorter_version_leaves_no_old_chunks(store):
    old = [_doc_chunk(f"upload://acme/r.txt#0::{i}", f"old {i}", "acme", 1, "r.txt") for i in range(3)]
    store.replace_document("acme", "r.txt", _vecs(3), old)
    new = [_doc_chunk("upload://acme/r.txt#0::0", "new 0", "acme", 1, "r.txt")]
    store.replace_document("acme", "r.txt", _vecs(1), new)
    assert _rows(store, "acme", "r.txt") == [("upload://acme/r.txt#0::0", "new 0", 1)]
    assert len(store) == 1


def test_replace_document_forbidden_changes_nothing(store):
    from consultrag.vectorstore import DocumentReplaceForbidden

    store.replace_document("acme", "r.txt", _vecs(2), [
        _doc_chunk("upload://acme/r.txt#0::0", "low part", "acme", 1, "r.txt"),
        _doc_chunk("upload://acme/r.txt#0::1", "high part", "acme", 3, "r.txt"),
    ])
    before = _rows(store, "acme", "r.txt")
    with pytest.raises(DocumentReplaceForbidden):
        store.replace_document(
            "acme", "r.txt", _vecs(1),
            [_doc_chunk("upload://acme/r.txt#0::0", "overwrite", "acme", 2, "r.txt")],
            max_existing_clearance=2,
        )
    assert _rows(store, "acme", "r.txt") == before
    # None = admin, no limit.
    store.replace_document(
        "acme", "r.txt", _vecs(1),
        [_doc_chunk("upload://acme/r.txt#0::0", "admin", "acme", 1, "r.txt")],
        max_existing_clearance=None,
    )
    assert _rows(store, "acme", "r.txt") == [("upload://acme/r.txt#0::0", "admin", 1)]


def test_replace_document_failure_rolls_back_and_connection_stays_usable(store):
    store.replace_document("acme", "r.txt", _vecs(2), [
        _doc_chunk("upload://acme/r.txt#0::0", "v1 a", "acme", 1, "r.txt"),
        _doc_chunk("upload://acme/r.txt#0::1", "v1 b", "acme", 1, "r.txt"),
    ])
    before = _rows(store, "acme", "r.txt")
    # Two new chunks with the same ID: the second INSERT violates the unique
    # constraint AFTER the delete already ran inside the transaction.
    dup = [
        _doc_chunk("upload://acme/r.txt#0::0", "v2 a", "acme", 1, "r.txt"),
        _doc_chunk("upload://acme/r.txt#0::0", "v2 dup", "acme", 1, "r.txt"),
    ]
    import psycopg

    with pytest.raises(psycopg.errors.UniqueViolation):
        store.replace_document("acme", "r.txt", _vecs(2), dup)
    assert _rows(store, "acme", "r.txt") == before
    # The shared connection was rolled back, not left in an aborted state.
    store.add(_vecs(1), [_doc_chunk("other", "still works", "acme", 1, "o.txt")])
    assert len(store) == 3


def test_replace_document_never_overwrites_another_documents_row(store):
    # Plain INSERT: a clashing chunk_id from a different document fails the
    # replacement instead of silently taking over that row.
    import psycopg

    store.add(_vecs(1), [_doc_chunk("clash", "globex text", "globex", 1, "g.txt")])
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.replace_document("acme", "a.txt", _vecs(1),
                               [_doc_chunk("clash", "acme text", "acme", 1, "a.txt")])
    assert _rows(store, "globex", "g.txt") == [("clash", "globex text", 1)]


def test_replace_document_same_name_in_two_engagements_stays_separate(store):
    store.replace_document("acme", "r.txt", _vecs(1),
                           [_doc_chunk("upload://acme/r.txt#0::0", "acme copy", "acme", 1, "r.txt")])
    store.replace_document("globex", "r.txt", _vecs(1),
                           [_doc_chunk("upload://globex/r.txt#0::0", "globex copy", "globex", 1, "r.txt")])
    store.replace_document("acme", "r.txt", _vecs(1),
                           [_doc_chunk("upload://acme/r.txt#0::0", "acme v2", "acme", 1, "r.txt")])
    assert _rows(store, "acme", "r.txt") == [("upload://acme/r.txt#0::0", "acme v2", 1)]
    assert _rows(store, "globex", "r.txt") == [("upload://globex/r.txt#0::0", "globex copy", 1)]


def test_replace_document_and_old_path_based_chunk_ids(store):
    # Chunks from path-based ingest use IDs like "<posix path>#<locator>::<n>".
    # Uploads use "upload://<engagement>/<name>#...", which no posix path can
    # produce (as_posix() collapses "//"), so the two formats never collide.
    store.add(_vecs(2), [
        _doc_chunk("data/sample/acme_research.txt#0::0", "path ingest", "acme", 1,
                   "data/sample/acme_research.txt"),
        _doc_chunk("acme_research.txt#0::0", "bare-name path ingest", "acme", 1,
                   "acme_research.txt"),
    ])
    store.replace_document("acme", "acme_research.txt", _vecs(1), [
        _doc_chunk("upload://acme/acme_research.txt#0::0", "uploaded", "acme", 1, "acme_research.txt"),
    ])
    # A same-engagement path-ingested chunk with the SAME bare name counts as
    # the same document and is replaced; a different path is untouched.
    assert _rows(store, "acme", "acme_research.txt") == [
        ("upload://acme/acme_research.txt#0::0", "uploaded", 1)
    ]
    assert _rows(store, "acme", "data/sample/acme_research.txt") == [
        ("data/sample/acme_research.txt#0::0", "path ingest", 1)
    ]
