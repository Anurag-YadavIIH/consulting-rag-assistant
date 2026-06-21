"""
Reranking: rescoring fused retrieval candidates with a model that judges
query-passage relevance directly, rather than via independently-computed
embeddings. This is the highest-ROI quality lever after hybrid retrieval.

Applied AFTER the access filter (see rag.py) — a chunk a user can't see never
reaches the reranker, or any model, in the first place.
"""

from __future__ import annotations

from typing import Protocol


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        ...


class NoOpReranker:
    """Passthrough — keeps the incoming (fused) order, just trims to top_k.
    Default so offline/test runs need no extra model download."""

    def rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        return candidates[:top_k]


class CrossEncoderReranker:
    """Local cross-encoder reranker (sentence-transformers CrossEncoder).
    Downloads BAAI/bge-reranker-base on first use — opt in via --rerank;
    disabled under --offline since it requires a model download."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        if not candidates:
            return []
        pairs = [(query, c["text"]) for c in candidates]
        scores = self._model.predict(pairs)
        scored = sorted(zip(candidates, scores), key=lambda cs: -cs[1])
        ranked = []
        for c, s in scored[:top_k]:
            c = dict(c)
            c["rerank_score"] = float(s)
            ranked.append(c)
        return ranked
