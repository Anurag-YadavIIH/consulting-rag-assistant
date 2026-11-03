"""
Postgres-backed tests for the pooled PgVectorStore (delete, list, connection
recovery, concurrent replacement) and the audit_events table (one event per
action, written in the change's own transaction, no question text or emails,
pagination, and admin-only access through the API).

Skipped cleanly if Postgres isn't reachable. Uses isolated tables for chunks;
audit rows are tagged with a test user ID prefix and deleted afterwards.
"""

import logging
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.config import settings
from consultrag.security.access import User
from consultrag.vectorstore import DocumentReplaceForbidden, StoredChunk


def _pg_available() -> bool:
    try:
        import psycopg
        import psycopg_pool  # noqa: F401
    except ImportError:
        return False
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="Postgres not reachable")

TEST_USER_PREFIX = "test-consultrag-audit-"


def _uid() -> str:
    return TEST_USER_PREFIX + uuid.uuid4().hex[:10]


@pytest.fixture
def store():
    from consultrag.pgvectorstore import PgVectorStore

    table = f"chunks_test_docs_{uuid.uuid4().hex[:8]}"
    s = PgVectorStore(dim=4, table_name=table)
    yield s
    with s.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute("SELECT to_regclass('audit_events')")
        if cur.fetchone()[0] is not None:
            cur.execute("DELETE FROM audit_events WHERE user_id LIKE %s", (TEST_USER_PREFIX + "%",))
    s.close()


@pytest.fixture
def audit(store):
    from consultrag.audit import PgAuditLog

    return PgAuditLog(store.pool)


def _chunk(cid, text, engagement, clearance, name, ingested_at=None):
    meta = {"engagement": engagement, "clearance": clearance, "source_path": name}
    if ingested_at:
        meta["ingested_at"] = ingested_at
    return StoredChunk(chunk_id=cid, text=text, metadata=meta)


def _vecs(n):
    return np.tile(np.array([[1, 0, 0, 0]], dtype=np.float32), (n, 1))


def _audit_rows(store, user_id):
    with store.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT event, engagement, document, n_chunks, redaction_counts, n_retrieved, n_blocked "
            "FROM audit_events WHERE user_id = %s ORDER BY id", (user_id,)
        )
        return cur.fetchall()


# --- delete and list --------------------------------------------------------------


def test_delete_document_removes_only_that_document(store):
    store.replace_document("acme", "a.txt", _vecs(2), [
        _chunk("upload://acme/a.txt#0::0", "a0", "acme", 1, "a.txt"),
        _chunk("upload://acme/a.txt#0::1", "a1", "acme", 1, "a.txt"),
    ])
    store.replace_document("acme", "b.txt", _vecs(1), [_chunk("upload://acme/b.txt#0::0", "b", "acme", 1, "b.txt")])
    store.replace_document("globex", "a.txt", _vecs(1), [_chunk("upload://globex/a.txt#0::0", "g", "globex", 1, "a.txt")])

    assert store.delete_document("acme", "a.txt") == 2
    names = sorted((c.metadata["engagement"], c.metadata["source_path"]) for c in store.all_chunks())
    assert names == [("acme", "b.txt"), ("globex", "a.txt")]
    assert store.delete_document("acme", "a.txt") == 0  # already gone
    assert store.delete_document("acme", "never.txt") == 0


def test_delete_document_with_a_hidden_chunk_changes_nothing(store):
    store.replace_document("acme", "mixed.txt", _vecs(2), [
        _chunk("upload://acme/mixed.txt#0::0", "low", "acme", 1, "mixed.txt"),
        _chunk("upload://acme/mixed.txt#0::1", "high", "acme", 3, "mixed.txt"),
    ])
    with pytest.raises(DocumentReplaceForbidden):
        store.delete_document("acme", "mixed.txt", max_existing_clearance=2)
    assert len(store) == 2
    assert store.delete_document("acme", "mixed.txt", max_existing_clearance=None) == 2  # admin


def test_list_documents_hides_documents_above_clearance_entirely(store):
    store.replace_document("acme", "open.txt", _vecs(2), [
        _chunk("upload://acme/open.txt#0::0", "o0", "acme", 1, "open.txt", "2026-11-03T10:00:00+00:00"),
        _chunk("upload://acme/open.txt#0::1", "o1", "acme", 1, "open.txt", "2026-11-03T10:00:00+00:00"),
    ])
    store.replace_document("acme", "mixed.txt", _vecs(2), [
        _chunk("upload://acme/mixed.txt#0::0", "m0", "acme", 1, "mixed.txt"),
        _chunk("upload://acme/mixed.txt#0::1", "m1", "acme", 3, "mixed.txt"),
    ])
    store.replace_document("globex", "g.txt", _vecs(1), [_chunk("upload://globex/g.txt#0::0", "g", "globex", 1, "g.txt")])

    assert store.list_documents("acme", max_clearance=2) == [
        {"name": "open.txt", "chunks": 2, "clearance": 1, "uploaded_at": "2026-11-03T10:00:00+00:00"},
    ]
    assert [d["name"] for d in store.list_documents("acme", max_clearance=3)] == ["mixed.txt", "open.txt"]
    assert store.list_documents("acme", max_clearance=3)[0]["uploaded_at"] is None  # older document


# --- the pool ----------------------------------------------------------------------


def test_pool_recovers_after_its_connections_are_killed(store):
    import psycopg

    store.add(_vecs(1), [_chunk("p1", "still here", "acme", 1, "p.txt")])
    assert len(store) == 1
    with psycopg.connect(settings.database_url, autocommit=True) as admin, admin.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE application_name = %s AND pid <> pg_backend_pid()",
            (f"consultrag-{store.table_name}",),
        )
        killed = cur.fetchall()
    assert killed, "expected to terminate at least one pooled connection"
    # The pool checks connections before handing them out and replaces dead ones.
    assert len(store) == 1
    assert store.search(_vecs(1)[0], top_k=1)[0]["chunk_id"] == "p1"
    store.add(_vecs(1), [_chunk("p2", "write after recovery", "acme", 1, "p.txt")])
    assert len(store) == 2


def test_concurrent_replacements_of_one_document_stay_atomic(store):
    # Without the old process-wide lock, the advisory lock and per-call
    # transactions must still leave exactly one complete version.
    def replace(version: int):
        n = version % 4 + 1
        store.replace_document("acme", "race.txt", _vecs(n), [
            _chunk(f"upload://acme/race.txt#0::{i}", f"v{version}", "acme", 1, "race.txt") for i in range(n)
        ])

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(replace, range(12)))
    texts = [c.text for c in store.all_chunks()]
    assert len(set(texts)) == 1
    version = int(texts[0][1:])
    assert len(texts) == version % 4 + 1


# --- audit_events -----------------------------------------------------------------


def test_one_audit_event_per_action_with_no_question_text_or_email(store, audit):
    from consultrag.embeddings import HashEmbedder
    from consultrag.pipeline import IngestionPipeline
    from consultrag.rag import RAGEngine

    user_id = _uid()
    embedder = HashEmbedder(dim=4)
    pipeline = IngestionPipeline(embedder=embedder, store=store, audit=audit)
    engine = RAGEngine(embedder=embedder, store=store, audit=audit)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "upload.txt"
        f.write_text("Contact jane.doe@example.com about the ACME_AUDIT_TOKEN pilot.")
        n = pipeline.ingest_path(f, engagement="acme", clearance=1, user_id=user_id,
                                 source_name="notes for bob@example.com.txt")
    question = "What did jane.doe@example.com say about SECRET_QUESTION_TOKEN?"
    engine.answer(question, User.make(user_id, roles=["analyst", "engagement:acme"]), engagement="acme")
    assert pipeline.delete_document("acme", "notes for bob@example.com.txt", user_id=user_id) == n

    rows = _audit_rows(store, user_id)
    assert [r[0] for r in rows] == ["ingest", "query", "delete"]
    ingest, query, delete = rows
    assert ingest[1] == "acme" and ingest[3] == n and ingest[4] == {"EMAIL": 1}
    assert query[1] == "acme" and query[5] >= 1 and query[6] == 0
    assert delete[1] == "acme" and delete[3] == n
    # Document names are redacted for the audit record (the email pattern
    # takes ".txt" as part of the domain); nothing else is free text.
    assert ingest[2] == delete[2] == "notes for [REDACTED_EMAIL]"
    with store.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT row_to_json(a)::text FROM audit_events a WHERE user_id = %s", (user_id,))
        dumped = " ".join(r[0] for r in cur.fetchall())
    for forbidden in ("SECRET_QUESTION_TOKEN", "jane.doe@example.com", "bob@example.com",
                      "ACME_AUDIT_TOKEN", "What did"):
        assert forbidden not in dumped


def test_failed_audit_write_rolls_back_the_upload_and_the_delete(store, audit, monkeypatch):
    import consultrag.audit as audit_mod

    user_id = _uid()
    store.replace_document("acme", "keep.txt", _vecs(1), [_chunk("upload://acme/keep.txt#0::0", "old", "acme", 1, "keep.txt")])

    def broken(cur, event):
        raise RuntimeError("audit table unavailable")

    monkeypatch.setattr(audit_mod, "insert_audit_event", broken)
    event = audit.ingest_event(user_id=user_id, engagement="acme", document="keep.txt",
                               n_chunks=1, redaction_counts={})
    with pytest.raises(RuntimeError):
        store.replace_document("acme", "keep.txt", _vecs(1),
                               [_chunk("upload://acme/keep.txt#0::0", "new", "acme", 1, "keep.txt")],
                               audit_event=event)
    assert [c.text for c in store.all_chunks()] == ["old"]

    with pytest.raises(RuntimeError):
        store.delete_document("acme", "keep.txt", audit_event_factory=lambda n: event)
    assert [c.text for c in store.all_chunks()] == ["old"]


def test_failed_audit_write_for_a_query_is_logged_and_the_query_succeeds(store, audit, monkeypatch, caplog):
    import consultrag.audit as audit_mod

    monkeypatch.setattr(audit_mod, "insert_audit_event",
                        lambda cur, event: (_ for _ in ()).throw(RuntimeError("down")))
    with caplog.at_level(logging.ERROR, logger="consultrag.audit"):
        audit.log_query(user_id=_uid(), query="SECRET_QUESTION_TOKEN?", retrieved_ids=["a"], n_blocked=0)
    assert any("audit write failed for a query event" in r.getMessage() for r in caplog.records)
    assert "SECRET_QUESTION_TOKEN" not in caplog.text


def test_recent_pages_newest_first(store, audit):
    from consultrag.audit import insert_audit_event

    user_id = _uid()
    with store.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        for i in range(5):
            insert_audit_event(cur, {"event": "query", "user_id": user_id, "n_retrieved": i, "n_blocked": 0})
    first = audit.recent(limit=2)
    assert [r["n_retrieved"] for r in first] == [4, 3]
    second = audit.recent(limit=2, before=first[-1]["id"])
    assert [r["n_retrieved"] for r in second] == [2, 1]
    assert first[0]["ts"].endswith("+00:00")  # UTC


# --- GET /admin/activity through the API ------------------------------------------


@pytest.fixture
def admin_client(store, audit, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from consultrag.api.deps import get_audit_log
    from consultrag.api.main import app

    monkeypatch.setattr(settings, "app_jwt_secret", "a-real-random-secret-for-audit-tests-1357")
    monkeypatch.setattr(settings, "dev_auth_bypass", False)
    app.dependency_overrides[get_audit_log] = lambda: audit
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _bearer(user: User) -> dict:
    from consultrag.auth.app_token import issue_app_token

    return {"Authorization": f"Bearer {issue_app_token(user, settings.app_jwt_secret)}"}


def test_admin_activity_requires_an_admin(admin_client):
    assert admin_client.get("/admin/activity").status_code == 401
    member = User.make("7", roles=["analyst", "engagement:acme", "engagement:globex"], clearance=5)
    resp = admin_client.get("/admin/activity", headers=_bearer(member))
    assert resp.status_code == 403 and resp.json() == {"detail": "admins only"}


def test_admin_activity_paginates_and_shows_ids_not_text(admin_client, store):
    from consultrag.audit import insert_audit_event

    user_id = _uid()
    with store.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        for i in range(3):
            insert_audit_event(cur, {"event": "ingest", "user_id": user_id, "engagement": "acme",
                                     "document": f"doc{i}.txt", "n_chunks": i + 1, "redaction_counts": {}})
    admin = User.make("99", roles=["admin"], clearance=5)
    page1 = admin_client.get("/admin/activity?limit=2", headers=_bearer(admin)).json()
    assert [e["document"] for e in page1["events"]] == ["doc2.txt", "doc1.txt"]
    assert page1["next_before"] == page1["events"][-1]["id"]
    assert set(page1["events"][0]) == {"id", "ts", "event", "user_id", "engagement", "document",
                                        "n_chunks", "redaction_counts", "n_retrieved", "n_blocked"}
    page2 = admin_client.get(f"/admin/activity?limit=2&before={page1['next_before']}",
                             headers=_bearer(admin)).json()
    assert page2["events"][0]["document"] == "doc0.txt"
    assert admin_client.get("/admin/activity?limit=500", headers=_bearer(admin)).status_code == 422


def test_admin_activity_filters_by_event_type(admin_client, store):
    from consultrag.audit import insert_audit_event

    user_id = _uid()
    with store.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        insert_audit_event(cur, {"event": "ingest", "user_id": user_id, "engagement": "acme",
                                 "document": "f.txt", "n_chunks": 1, "redaction_counts": {}})
        insert_audit_event(cur, {"event": "query", "user_id": user_id, "n_retrieved": 2, "n_blocked": 0})
        insert_audit_event(cur, {"event": "delete", "user_id": user_id, "engagement": "acme",
                                 "document": "f.txt", "n_chunks": 1})
    admin = User.make("99", roles=["admin"], clearance=5)
    for event in ("ingest", "query", "delete"):
        body = admin_client.get(f"/admin/activity?event={event}&limit=200", headers=_bearer(admin)).json()
        mine = [e for e in body["events"] if e["user_id"] == user_id]
        assert [e["event"] for e in mine] == [event]
        assert all(e["event"] == event for e in body["events"])
    assert admin_client.get("/admin/activity?event=bogus", headers=_bearer(admin)).status_code == 422
    member = User.make("7", roles=["analyst", "engagement:acme"], clearance=5)
    assert admin_client.get("/admin/activity?event=query", headers=_bearer(member)).status_code == 403
