import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.retrieval import BM25Index, HybridRetriever, _rrf_fuse
from consultrag.vectorstore import NumpyVectorStore, StoredChunk

import numpy as np


def _item(cid, score=0.0):
    return {"chunk_id": cid, "text": cid, "metadata": {}, "score": score}


def test_rrf_fuse_hand_computed():
    # dense ranks: a(1) b(2) c(3); bm25 ranks: b(1) c(2) a(3)
    dense = [_item("a"), _item("b"), _item("c")]
    bm25 = [_item("b"), _item("c"), _item("a")]
    fused = _rrf_fuse([dense, bm25], k=60)

    expected = {
        "a": 1 / 61 + 1 / 63,
        "b": 1 / 62 + 1 / 61,
        "c": 1 / 63 + 1 / 62,
    }
    by_id = {it["chunk_id"]: it["rrf_score"] for it in fused}
    for cid, score in expected.items():
        assert abs(by_id[cid] - score) < 1e-9
    # b has the highest combined score (rank 2 + rank 1)
    assert fused[0]["chunk_id"] == "b"


def test_rrf_fuse_disjoint_result_sets_unions_them():
    dense = [_item("a"), _item("b"), _item("c")]
    bm25 = [_item("d"), _item("e"), _item("f")]
    fused = _rrf_fuse([dense, bm25], k=60)
    assert {it["chunk_id"] for it in fused} == {"a", "b", "c", "d", "e", "f"}
    # each item only appears once even though it was only ranked in one list
    assert len(fused) == 6
    # top item from each list (rank 1) ties, both ahead of every rank-2/3 item
    assert {fused[0]["chunk_id"], fused[1]["chunk_id"]} == {"a", "d"}


def test_bm25_index_empty_corpus_returns_no_crash():
    index = BM25Index(chunks=[])
    assert index.search("anything", top_k=5) == []


def test_hybrid_retriever_falls_back_to_dense_only_when_bm25_empty():
    # Store has chunks (so dense search works), but we hand HybridRetriever an
    # empty BM25Index snapshot to simulate "ingested after the retriever was
    # built and never refreshed" — fusion should degrade gracefully to
    # dense-only ranking, not crash or drop everything.
    store = NumpyVectorStore(dim=4)
    vectors = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
    chunks = [
        StoredChunk(chunk_id="x", text="alpha", metadata={}),
        StoredChunk(chunk_id="y", text="beta", metadata={}),
    ]
    store.add(vectors, chunks)

    retriever = HybridRetriever(store)
    retriever._bm25 = BM25Index(chunks=[])  # simulate stale/empty BM25 snapshot

    qvec = np.array([1, 0, 0, 0], dtype=np.float32)
    results = retriever.retrieve(qvec, "alpha", fused_k=5)
    assert [r["chunk_id"] for r in results] == ["x", "y"]
