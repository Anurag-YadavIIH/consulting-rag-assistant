#!/usr/bin/env python3
"""Run retrieval evaluation against eval/eval_set.jsonl.

Hybrid retrieval (dense + BM25 via RRF) is always on; --rerank additionally
applies the cross-encoder reranker. This measures raw retrieval/ranking
quality only — no access-control filtering (see consultrag.eval.evaluate's
docstring); RBAC correctness is covered by tests/test_pipeline.py instead.

--store {numpy,pgvector} lets you run the same eval set against both backends
and confirm hit@k/recall@k/MRR match within float tolerance — an equivalence
check that the PgVectorStore migration didn't change retrieval behavior, not
a test of RBAC (which neither backend applies here).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _cli_common import add_embedder_args, build_embedder, resolve_network_policy

from consultrag.eval import load_eval_set, evaluate
from consultrag.reranking import CrossEncoderReranker, NoOpReranker
from consultrag.vectorstore import NumpyVectorStore

ap = argparse.ArgumentParser()
ap.add_argument("--index", default="index")
ap.add_argument("--eval-set", default="eval/eval_set.jsonl")
ap.add_argument("--k", type=int, default=5)
ap.add_argument("--table", default="chunks", help="pgvector table name (--store pgvector only)")
add_embedder_args(ap, include_rerank=True)
args = ap.parse_args()
resolve_network_policy(args, ap)

embedder = build_embedder(args.embedder)
reranker = CrossEncoderReranker() if args.rerank else NoOpReranker()

if args.store == "pgvector":
    from consultrag.pgvectorstore import PgVectorStore

    store = PgVectorStore.load(dim=embedder.dim, table_name=args.table)
else:
    store = NumpyVectorStore.load(args.index)

items = load_eval_set(args.eval_set)
metrics = evaluate(embedder, store, items, k=args.k, reranker=reranker)
print("Retrieval metrics:")
for key, val in metrics.items():
    print(f"  {key:12s}: {val}")
