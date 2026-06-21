"""
Retrieval evaluation.

"Did it retrieve the right thing?" is the question that separates a real RAG
project from a tutorial. We score retrieval against a small hand-labeled set:
each eval item is a question plus the chunk_id(s) that genuinely answer it.

Metrics:
  * hit@k   — fraction of questions where a relevant chunk appears in the top k
  * recall@k— fraction of all relevant chunks that were retrieved
  * MRR     — mean reciprocal rank of the first relevant chunk (rewards ranking
              the right passage near the top, not just including it)

Building even a 15-30 question gold set by hand, and reporting these numbers in
your README, is the single most credible thing you can show.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .embeddings import Embedder
from .reranking import NoOpReranker, Reranker
from .retrieval import HybridRetriever, Retriever
from .vectorstore import NumpyVectorStore


@dataclass
class EvalItem:
    question: str
    relevant_ids: list[str]


def load_eval_set(path: str | Path) -> list[EvalItem]:
    items: list[EvalItem] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            items.append(EvalItem(d["question"], d["relevant_ids"]))
    return items


def evaluate(
    embedder: Embedder,
    store: NumpyVectorStore,
    items: list[EvalItem],
    k: int = 5,
    retriever: Retriever | None = None,
    reranker: Reranker | None = None,
    fused_k: int = 20,
) -> dict:
    """Retrieval-only metrics — hybrid retrieval + optional reranking, with NO
    access-control filtering. RBAC correctness is covered separately by
    tests/test_pipeline.py's end-to-end access-control tests; this eval
    measures raw retrieval/ranking quality only."""
    retriever = retriever or HybridRetriever(store)
    reranker = reranker or NoOpReranker()
    hits = 0
    rr_sum = 0.0
    recall_sum = 0.0

    for item in items:
        qvec = embedder.embed([item.question])[0]
        fused = retriever.retrieve(qvec, item.question, fused_k=max(fused_k, k))
        results = reranker.rerank(item.question, fused, top_k=k)
        retrieved = [r["chunk_id"] for r in results]
        relevant = set(item.relevant_ids)

        # hit@k
        if any(cid in relevant for cid in retrieved):
            hits += 1
        # MRR
        for rank, cid in enumerate(retrieved, start=1):
            if cid in relevant:
                rr_sum += 1.0 / rank
                break
        # recall@k
        if relevant:
            found = len(relevant & set(retrieved))
            recall_sum += found / len(relevant)

    n = len(items) or 1
    return {
        "n_questions": len(items),
        "k": k,
        "hit@k": round(hits / n, 3),
        "mrr": round(rr_sum / n, 3),
        "recall@k": round(recall_sum / n, 3),
    }
