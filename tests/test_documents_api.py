"""
GET /documents, DELETE /documents and citation passages, through the API with
an in-memory store (no Postgres). Covers 401, no access, wrong engagement,
clearance and hidden-document behaviour, redacted citation text, and that a
deleted document is gone from both dense and keyword search without a
restart.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("jwt", reason="pyjwt[crypto] not installed")
pytest.importorskip("fastapi", reason="fastapi not installed")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from consultrag.api.deps import get_audit_log, get_ingestion_pipeline, get_rag_engine
from consultrag.api.main import app
from consultrag.audit import AuditLog
from consultrag.auth.app_token import issue_app_token
from consultrag.config import settings
from consultrag.embeddings import HashEmbedder
from consultrag.pipeline import IngestionPipeline
from consultrag.rag import RAGEngine
from consultrag.security.access import User
from consultrag.vectorstore import NumpyVectorStore

SECRET = "a-real-random-secret-for-documents-tests-2468"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "dev_auth_bypass", False)
    embedder = HashEmbedder(dim=256)
    store = NumpyVectorStore(dim=256)
    audit = AuditLog(tmp_path / "audit.log")
    pipeline = IngestionPipeline(embedder=embedder, store=store, audit=audit)
    engine = RAGEngine(embedder=embedder, store=store)

    def put(name, text, engagement="acme", clearance=1):
        f = tmp_path / "upload.txt"
        f.write_text(text)
        return pipeline.ingest_path(f, engagement=engagement, clearance=clearance,
                                    source_name=name, user_id="seed")

    put("open.txt", "Acme OPEN_TOKEN reimbursement analysis for the pilot.")
    put("board.txt", "Acme BOARD_TOKEN minutes about the acquisition.", clearance=3)
    put("globex.txt", "Globex GLOBEX_TOKEN neuromonitoring plan.", engagement="globex")
    engine.retriever.refresh()

    app.dependency_overrides[get_rag_engine] = lambda: engine
    app.dependency_overrides[get_ingestion_pipeline] = lambda: pipeline
    app.dependency_overrides[get_audit_log] = lambda: audit
    with TestClient(app) as c:
        yield c, store, engine, pipeline, put, audit
    app.dependency_overrides.clear()


def _bearer(user: User) -> dict:
    return {"Authorization": f"Bearer {issue_app_token(user, SECRET)}"}


def analyst(clearance=2):
    return User.make("1", roles=["analyst", "engagement:acme"], clearance=clearance)


def nobody():
    return User.make("2", roles=[], clearance=1)


def admin():
    return User.make("99", roles=["admin"], clearance=5)


# --- GET /documents ---------------------------------------------------------------


def test_list_documents_needs_a_token(env):
    c, *_ = env
    assert c.get("/documents?engagement=acme").status_code == 401


def test_list_documents_no_access_and_wrong_engagement_are_403(env):
    c, *_ = env
    resp = c.get("/documents?engagement=acme", headers=_bearer(nobody()))
    assert resp.status_code == 403 and resp.json()["detail"].startswith("no access yet")
    resp = c.get("/documents?engagement=globex", headers=_bearer(analyst()))
    assert resp.status_code == 403 and set(resp.json()) == {"detail"}


def test_list_documents_hides_documents_above_clearance(env):
    c, *_ = env
    docs = c.get("/documents?engagement=acme", headers=_bearer(analyst(clearance=2))).json()["documents"]
    assert [d["name"] for d in docs] == ["open.txt"]  # board.txt (clearance 3) isn't shown or counted
    assert docs[0]["chunks"] == 1 and docs[0]["clearance"] == 1
    assert docs[0]["uploaded_at"].endswith("+00:00")  # UTC

    high = c.get("/documents?engagement=acme", headers=_bearer(analyst(clearance=3))).json()["documents"]
    assert [d["name"] for d in high] == ["board.txt", "open.txt"]


def test_list_documents_admin_sees_any_engagement_within_clearance(env):
    c, *_ = env
    docs = c.get("/documents?engagement=globex", headers=_bearer(admin())).json()
    assert docs == {"engagement": "globex", "documents": [
        {"name": "globex.txt", "chunks": 1, "clearance": 1, "uploaded_at": docs["documents"][0]["uploaded_at"]}
    ]}


def test_list_documents_reports_null_upload_time_for_older_documents(env):
    c, store, *_ = env
    for chunk in store.all_chunks():
        chunk.metadata.pop("ingested_at", None)
    docs = c.get("/documents?engagement=acme", headers=_bearer(analyst())).json()["documents"]
    assert docs[0]["uploaded_at"] is None


# --- DELETE /documents --------------------------------------------------------------


def test_delete_needs_a_token(env):
    c, *_ = env
    assert c.delete("/documents?engagement=acme&name=open.txt").status_code == 401


def test_delete_no_access_and_wrong_engagement_are_403(env):
    c, store, *_ = env
    assert c.delete("/documents?engagement=acme&name=open.txt", headers=_bearer(nobody())).status_code == 403
    assert c.delete("/documents?engagement=globex&name=globex.txt", headers=_bearer(analyst())).status_code == 403
    assert len(store) == 3


def test_delete_hidden_document_is_the_same_404_as_a_missing_one(env):
    c, store, *_ = env
    hidden = c.delete("/documents?engagement=acme&name=board.txt", headers=_bearer(analyst(clearance=2)))
    missing = c.delete("/documents?engagement=acme&name=nope.txt", headers=_bearer(analyst(clearance=2)))
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json() == {"detail": "no such document in this engagement"}
    assert len(store) == 3  # nothing deleted


def test_admin_can_delete_a_document_above_an_analysts_clearance(env):
    c, store, *_ = env
    resp = c.delete("/documents?engagement=acme&name=board.txt", headers=_bearer(admin()))
    assert resp.status_code == 200 and resp.json() == {"name": "board.txt", "chunks_deleted": 1}
    assert len(store) == 2


def test_deleted_document_disappears_from_both_searches_without_restart(env):
    c, store, engine, *_ = env
    user = analyst()
    before = c.post("/query", json={"question": "OPEN_TOKEN reimbursement", "engagement": "acme"},
                    headers=_bearer(user)).json()
    assert any(cit["source_path"] == "open.txt" for cit in before["citations"])

    resp = c.delete("/documents?engagement=acme&name=open.txt", headers=_bearer(user))
    assert resp.status_code == 200 and resp.json()["chunks_deleted"] == 1

    # Keyword (BM25) index of this process was refreshed, and dense search
    # reads the store directly.
    assert all(h["metadata"]["source_path"] != "open.txt"
               for h in engine.retriever._bm25.search("OPEN_TOKEN", top_k=10))
    qvec = engine.embedder.embed(["OPEN_TOKEN reimbursement"])[0]
    assert all(h["metadata"]["source_path"] != "open.txt" for h in store.search(qvec, top_k=10))
    after = c.post("/query", json={"question": "OPEN_TOKEN reimbursement", "engagement": "acme"},
                   headers=_bearer(user)).json()
    assert all(cit["source_path"] != "open.txt" for cit in after["citations"])
    assert "OPEN_TOKEN" not in after["answer"]


def test_delete_is_written_to_the_audit_log(env):
    c, _, _, _, _, audit = env
    c.delete("/documents?engagement=acme&name=open.txt", headers=_bearer(analyst()))
    last = audit.path.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert '"event": "delete"' in last and '"source_path": "open.txt"' in last and '"n_chunks": 1' in last


# --- citations ----------------------------------------------------------------------


def test_citations_carry_number_and_redacted_text(env):
    c, _, engine, _, put, _ = env
    put("contact.txt", "Call jane.doe@example.com about the CONTACT_TOKEN pricing review.")
    engine.retriever.refresh()
    resp = c.post("/query", json={"question": "CONTACT_TOKEN pricing review", "engagement": "acme"},
                  headers=_bearer(analyst()))
    cits = resp.json()["citations"]
    assert [cit["number"] for cit in cits] == list(range(1, len(cits) + 1))
    contact = next(cit for cit in cits if cit["source_path"] == "contact.txt")
    assert "CONTACT_TOKEN" in contact["text"]
    assert "jane.doe@example.com" not in contact["text"] and "[REDACTED_EMAIL]" in contact["text"]
    # Extractive mode answers with the first passage, labelled [1].
    assert resp.json()["answer"].count("[1]") >= 1


def test_citation_text_never_includes_chunks_the_user_cannot_see(env):
    c, *_ = env
    resp = c.post("/query", json={"question": "BOARD_TOKEN minutes acquisition GLOBEX_TOKEN"},
                  headers=_bearer(analyst(clearance=2)))
    body = resp.json()
    texts = " ".join(cit["text"] for cit in body["citations"])
    assert "BOARD_TOKEN" not in texts and "GLOBEX_TOKEN" not in texts


def test_draft_citations_have_number_and_text(env):
    c, *_ = env
    resp = c.post("/draft", json={"topic": "OPEN_TOKEN reimbursement", "engagement": "acme"},
                  headers=_bearer(analyst()))
    cit = resp.json()["citations"][0]
    assert cit["number"] == 1 and "OPEN_TOKEN" in cit["text"]


# --- answer structure: mode and quotes ------------------------------------------------


def test_extractive_answer_returns_structured_quotes_and_unchanged_text(env):
    c, *_ = env
    body = c.post("/query", json={"question": "OPEN_TOKEN reimbursement", "engagement": "acme"},
                  headers=_bearer(analyst())).json()
    assert body["mode"] == "extractive"
    assert body["quotes"] == [{"number": 1, "text": body["citations"][0]["text"]}]
    # The plain-text answer is untouched for the CLI and older clients.
    assert body["answer"].startswith("Based on the retrieved material:")
    assert "[1] Source: open.txt" in body["answer"]


def test_draft_returns_the_same_structure(env):
    c, *_ = env
    body = c.post("/draft", json={"topic": "OPEN_TOKEN reimbursement", "engagement": "acme"},
                  headers=_bearer(analyst())).json()
    assert body["mode"] == "extractive" and body["quotes"][0]["number"] == 1
    assert body["draft"].startswith("Based on the retrieved material:")


def test_not_found_is_identical_for_empty_and_hidden_only_engagements(env):
    c, _, engine, _, put, _ = env
    put("secret_only.txt", "Initech SECRET_INITECH_TOKEN board plan.", engagement="initech", clearance=3)
    engine.retriever.refresh()
    hidden_only = User.make("5", roles=["analyst", "engagement:initech"], clearance=1)
    empty = User.make("6", roles=["analyst", "engagement:hooli"], clearance=1)
    q = {"question": "SECRET_INITECH_TOKEN board plan"}
    a = c.post("/query", json={**q, "engagement": "initech"}, headers=_bearer(hidden_only)).json()
    b = c.post("/query", json={**q, "engagement": "hooli"}, headers=_bearer(empty)).json()
    expected = {"answer": "I couldn't find this in the documents you can access.",
                "citations": [], "mode": "extractive", "quotes": []}
    assert a == expected and b == expected


def test_generative_mode_has_no_quotes():
    from consultrag.embeddings import HashEmbedder as HE

    class Writer:
        def complete(self, system, user):
            return "A written summary citing [1]."

    store = NumpyVectorStore(dim=64)
    pipeline = IngestionPipeline(embedder=HE(dim=64), store=store)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.txt"
        f.write_text("Some acme text.")
        pipeline.ingest_path(f, engagement="acme")
    engine = RAGEngine(embedder=HE(dim=64), store=store, llm=Writer())
    ans = engine.answer("acme text", analyst(), engagement="acme")
    assert ans.mode == "generative" and ans.quotes == [] and ans.text == "A written summary citing [1]."


def test_citation_scores_say_what_they_measure(env):
    c, *_ = env
    body = c.post("/query", json={"question": "OPEN_TOKEN reimbursement", "engagement": "acme"},
                  headers=_bearer(analyst())).json()
    assert body["citations"]
    for cit in body["citations"]:
        assert cit["score_kind"] in ("similarity", "keyword")
        if cit["score_kind"] == "similarity":
            assert -1.0 <= cit["score"] <= 1.0


def test_hybrid_retriever_labels_dense_and_keyword_only_results():
    import numpy as np

    from consultrag.retrieval import HybridRetriever
    from consultrag.vectorstore import StoredChunk

    store = NumpyVectorStore(dim=4)
    store.add(np.array([[1, 0, 0, 0], [0.9, 0.1, 0, 0], [0, 0, 1, 0]], dtype=np.float32), [
        StoredChunk(chunk_id="dense1", text="unrelated words", metadata={}),
        StoredChunk(chunk_id="dense2", text="other words", metadata={}),
        StoredChunk(chunk_id="kw", text="ZEBRA token here", metadata={}),
    ])
    # Dense returns only the two closest (kw is far away), so kw can only
    # arrive through the keyword leg.
    r = HybridRetriever(store, dense_k=2, bm25_k=1)
    out = {i["chunk_id"]: i["score_kind"]
           for i in r.retrieve(np.array([1, 0, 0, 0], dtype=np.float32), "ZEBRA", fused_k=2)}
    assert out["dense1"] == "similarity"
    assert out["kw"] == "keyword"
