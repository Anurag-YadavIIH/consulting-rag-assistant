"""
Hybrid retrieval: dense (vector store cosine) search fused with sparse (BM25
keyword) search via Reciprocal Rank Fusion (RRF).

Pure-dense search misses exact-token matches — drug names, device models,
billing codes, company names — that consulting queries often hinge on. BM25
recovers those. RRF combines the two differently-scaled ranked lists into one
without needing to normalize or weight raw scores against each other: it only
looks at each item's *rank* in each list.
"""

from __future__ import annotations

import re
from typing import Protocol

from rank_bm25 import BM25Okapi

from .vectorstore import NumpyVectorStore, StoredChunk

# Standard RRF damping constant (Cormack, Clarke & Buettcher 2009). Both
# rankers are weighted equally for now — weighting dense vs. sparse
# contributions differently is a future tuning knob, not implemented here.
RRF_K = 60

_TOKEN_RE = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class Retriever(Protocol):
    def retrieve(self, query_vec, query_text: str, fused_k: int, user=None) -> list[dict]:
        ...


class BM25Index:
    """BM25 over the chunk text currently held by a vector store."""

    def __init__(self, chunks: list[StoredChunk]):
        self._chunks = list(chunks)
        # BM25Okapi divides by the number of distinct terms in the corpus, so
        # it can't be constructed over zero documents — leave it unset and
        # let search() short-circuit on the empty-chunks check below instead.
        self._bm25 = (
            BM25Okapi([_tokenize(c.text) for c in self._chunks]) if self._chunks else None
        )

    @classmethod
    def from_store(cls, store: NumpyVectorStore) -> "BM25Index":
        return cls(store.all_chunks())

    def search(self, query_text: str, top_k: int) -> list[dict]:
        if not self._chunks:
            return []
        scores = self._bm25.get_scores(_tokenize(query_text))
        k = min(top_k, len(self._chunks))
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        results = []
        for i in ranked:
            c = self._chunks[i]
            results.append(
                {
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "metadata": c.metadata,
                    "score": float(scores[i]),
                }
            )
        return results


def _rrf_fuse(ranked_lists: list[list[dict]], k: int = RRF_K) -> list[dict]:
    """Reciprocal Rank Fusion over any number of ranked result lists, keyed by
    chunk_id. Only rank position matters, not the raw per-list score — so a
    list with zero genuinely relevant hits can still nudge its top item up
    purely by being first in that list. That's a known property of RRF, not a
    bug; see tests/test_retrieval.py for the degenerate case."""
    fused: dict[str, dict] = {}
    rrf_scores: dict[str, float] = {}
    for results in ranked_lists:
        for rank, item in enumerate(results, start=1):
            cid = item["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in fused:
                fused[cid] = item
    ordered = sorted(fused.values(), key=lambda it: -rrf_scores[it["chunk_id"]])
    for item in ordered:
        item["rrf_score"] = rrf_scores[item["chunk_id"]]
    return ordered


class HybridRetriever:
    """Wraps a NumpyVectorStore: fuses dense cosine search with BM25 keyword
    search via RRF.

    The BM25 index is a snapshot taken at construction time. Call .refresh()
    after ingesting new chunks into the store so BM25 picks them up — dense
    search always reads live since it queries the store directly."""

    def __init__(
        self,
        store: NumpyVectorStore,
        dense_k: int = 20,
        bm25_k: int = 20,
        rrf_k: int = RRF_K,
    ):
        self.store = store
        self.dense_k = dense_k
        self.bm25_k = bm25_k
        self.rrf_k = rrf_k
        self._bm25 = BM25Index.from_store(store)

    def refresh(self) -> None:
        self._bm25 = BM25Index.from_store(self.store)

    def retrieve(self, query_vec, query_text: str, fused_k: int, user=None) -> list[dict]:
        # `user`, if given, lets the store apply a defense-in-depth SQL filter
        # on the dense leg (PgVectorStore does; NumpyVectorStore ignores it).
        # The BM25 leg always searches the full local snapshot — both legs
        # still pass through AccessPolicy.filter() afterward regardless.
        dense = self.store.search(query_vec, top_k=max(self.dense_k, fused_k), user=user)
        sparse = self._bm25.search(query_text, top_k=max(self.bm25_k, fused_k))
        fused = _rrf_fuse([dense, sparse], k=self.rrf_k)
        return fused[:fused_k]
