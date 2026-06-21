import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.embeddings import HashEmbedder
from consultrag.pipeline import IngestionPipeline
from consultrag.rag import RAGEngine
from consultrag.security.access import AccessPolicy, User
from consultrag.vectorstore import NumpyVectorStore


def build(tmp_path):
    # two engagements, separate confidential docs
    (tmp_path / "acme.txt").write_text(
        "Acme is evaluating an ambulatory neurosurgical navigation platform. "
        "The market for intraoperative imaging is growing at 12 percent annually. "
        "Reimbursement risk is the main barrier to adoption."
    )
    (tmp_path / "globex.txt").write_text(
        "Globex is exploring a remote neuromonitoring subscription model. "
        "Their pilot showed strong retention among teaching hospitals."
    )
    embedder = HashEmbedder(dim=256)
    store = NumpyVectorStore(dim=256)
    pipe = IngestionPipeline(embedder=embedder, store=store)
    pipe.ingest_path(tmp_path / "acme.txt", engagement="acme", clearance=2)
    pipe.ingest_path(tmp_path / "globex.txt", engagement="globex", clearance=2)
    return embedder, store


def test_end_to_end_retrieval(tmp_path):
    embedder, store = build(tmp_path)
    engine = RAGEngine(embedder=embedder, store=store,
                       access_policy=AccessPolicy(), top_k=3)
    user = User.make("u1", roles=["analyst", "engagement:acme"], clearance=2)
    ans = engine.answer("What is the barrier to adoption for Acme?", user)
    assert ans.used_chunks, "should retrieve something"
    # every returned chunk must belong to acme (access control held)
    for c in ans.used_chunks:
        assert c["metadata"].get("engagement") == "acme"


def test_access_control_blocks_other_engagement(tmp_path):
    embedder, store = build(tmp_path)
    engine = RAGEngine(embedder=embedder, store=store, top_k=5)
    # user only cleared for acme should never see globex chunks
    user = User.make("u1", roles=["analyst", "engagement:acme"], clearance=2)
    results = engine.retrieve("neuromonitoring subscription retention", user)
    for c in results:
        assert c["metadata"].get("engagement") != "globex"


def test_clearance_enforced(tmp_path):
    embedder, store = build(tmp_path)
    engine = RAGEngine(embedder=embedder, store=store, top_k=5)
    # clearance 1 user cannot see clearance-2 material
    low = User.make("u2", roles=["analyst", "engagement:acme"], clearance=1)
    results = engine.retrieve("imaging market growth", low)
    assert results == []
