import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.embeddings import HashEmbedder
from consultrag.rag import RAGEngine
from consultrag.reranking import NoOpReranker
from consultrag.security.access import User
from consultrag.vectorstore import NumpyVectorStore


class FakeRetriever:
    """Test double: returns a fixed, known fused candidate order regardless
    of the query, isolating the reranker-wiring test from BM25/RRF behavior
    (covered separately in test_retrieval.py)."""

    def __init__(self, results):
        self._results = results

    def retrieve(self, query_vec, query_text, fused_k, user=None):
        return list(self._results)


class FakeReranker:
    """Test double: deterministically reverses input order. If RAGEngine
    actually applies the reranker's output (rather than the pre-rerank fused
    order), the returned order must be exactly reversed."""

    def rerank(self, query, candidates, top_k):
        return list(reversed(candidates))[:top_k]


def _candidates():
    return [
        {"chunk_id": "a", "text": "a", "metadata": {}, "score": 0.9},
        {"chunk_id": "b", "text": "b", "metadata": {}, "score": 0.5},
        {"chunk_id": "c", "text": "c", "metadata": {}, "score": 0.1},
    ]


def test_reranker_output_order_is_applied():
    engine = RAGEngine(
        embedder=HashEmbedder(dim=8),
        store=NumpyVectorStore(dim=8),
        retriever=FakeRetriever(_candidates()),
        reranker=FakeReranker(),
        top_k=3,
    )
    user = User.make("u", roles=["admin"], clearance=5)
    out = engine.retrieve("q", user)
    assert [c["chunk_id"] for c in out] == ["c", "b", "a"]


def test_noop_reranker_preserves_fused_order_and_trims():
    engine = RAGEngine(
        embedder=HashEmbedder(dim=8),
        store=NumpyVectorStore(dim=8),
        retriever=FakeRetriever(_candidates()),
        reranker=NoOpReranker(),
        top_k=2,
    )
    user = User.make("u", roles=["admin"], clearance=5)
    out = engine.retrieve("q", user)
    assert [c["chunk_id"] for c in out] == ["a", "b"]


def test_reranker_only_sees_access_filtered_candidates():
    # one candidate belongs to an engagement the user can't see — the
    # reranker (and any model behind it) must never receive it.
    candidates = _candidates()
    candidates[0]["metadata"] = {"engagement": "globex"}
    engine = RAGEngine(
        embedder=HashEmbedder(dim=8),
        store=NumpyVectorStore(dim=8),
        retriever=FakeRetriever(candidates),
        reranker=FakeReranker(),
        top_k=3,
    )
    user = User.make("u", roles=["analyst", "engagement:acme"], clearance=5)
    out = engine.retrieve("q", user)
    assert "a" not in [c["chunk_id"] for c in out]
    assert [c["chunk_id"] for c in out] == ["c", "b"]
