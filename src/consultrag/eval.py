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
    # answerable: relevant_ids is the real supporting chunk(s).
    # partial: relevant_ids is the real context chunk(s), but the corpus is
    #   missing some specific detail the question asks for — a correct
    #   generation should retrieve the context and then abstain on the
    #   missing specific, not invent it. Scored on retrieval like answerable.
    # unanswerable: relevant_ids is empty — no chunk can legitimately satisfy
    #   this question. Excluded from retrieval metrics entirely (see
    #   evaluate()'s docstring) since "nothing relevant exists" isn't a
    #   retrieval failure to score against.
    category: str = "answerable"


def load_eval_set(path: str | Path) -> list[EvalItem]:
    items: list[EvalItem] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            items.append(
                EvalItem(d["question"], d["relevant_ids"], d.get("category", "answerable"))
            )
    return items


def validate_relevant_ids(
    items: list[EvalItem], known_chunk_ids: set[str]
) -> list[tuple[str, str]]:
    """Returns (question, bad_id) for every non-empty relevant_id that
    doesn't match a real chunk_id in known_chunk_ids. Empty list means the
    eval set is fully valid against that corpus. This is the check that
    would have caught the chunk-ID scheme bugs immediately instead of
    silently scoring 0.0 — re-run it after any re-ingest."""
    problems: list[tuple[str, str]] = []
    for item in items:
        for rid in item.relevant_ids:
            if rid not in known_chunk_ids:
                problems.append((item.question, rid))
    return problems


def check_multi_source_coverage(
    items: list[EvalItem],
    embedder: Embedder,
    retriever: Retriever,
    reranker: Reranker,
    k: int = 5,
    fused_k: int = 20,
) -> list[dict]:
    """For every item with more than one relevant_id, runs retrieval and
    reports which labeled chunks never surface in the top-k — a stricter,
    per-label check than hit@k (which only requires ONE match to count as a
    hit). Distinguishes a genuinely bad multi-source label from a real
    retrieval gap, which a passing hit@k alone can hide."""
    problems: list[dict] = []
    for item in items:
        if len(item.relevant_ids) <= 1:
            continue
        qvec = embedder.embed([item.question])[0]
        fused = retriever.retrieve(qvec, item.question, fused_k=fused_k)
        ranked = reranker.rerank(item.question, fused, top_k=k)
        retrieved_ids = [r["chunk_id"] for r in ranked]
        missing = [rid for rid in item.relevant_ids if rid not in retrieved_ids]
        if missing:
            problems.append(
                {
                    "question": item.question,
                    "relevant_ids": item.relevant_ids,
                    "missing": missing,
                    "top_k_retrieved": retrieved_ids,
                }
            )
    return problems


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
    measures raw retrieval/ranking quality only.

    Scored over 'answerable' + 'partial' items only. 'unanswerable' items
    (relevant_ids == [], nothing in the corpus can legitimately satisfy them)
    are excluded from hit@k/recall@k/MRR entirely — counted and reported,
    but never scored as automatic misses, since "correctly found nothing
    because nothing relevant exists" isn't a retrieval failure."""
    retriever = retriever or HybridRetriever(store)
    reranker = reranker or NoOpReranker()

    scored_items = [it for it in items if it.category in ("answerable", "partial")]
    n_answerable = sum(1 for it in items if it.category == "answerable")
    n_partial = sum(1 for it in items if it.category == "partial")
    n_unanswerable = sum(1 for it in items if it.category == "unanswerable")

    hits = 0
    rr_sum = 0.0
    recall_sum = 0.0

    for item in scored_items:
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

    n = len(scored_items) or 1
    return {
        "scope": "answerable + partial (unanswerable excluded)",
        "n_questions_total": len(items),
        "n_answerable": n_answerable,
        "n_partial": n_partial,
        "n_unanswerable_excluded": n_unanswerable,
        "n_scored": len(scored_items),
        "k": k,
        "hit@k": round(hits / n, 3),
        "mrr": round(rr_sum / n, 3),
        "recall@k": round(recall_sum / n, 3),
    }
