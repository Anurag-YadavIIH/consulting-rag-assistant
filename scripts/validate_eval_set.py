#!/usr/bin/env python3
"""Validate an eval set against a real index: every relevant_id must match
an actual chunk_id, and every multi-source label's chunks should actually
surface in top-k retrieval (a stricter, per-label check than hit@k, which
only needs ONE match to count as a hit).

Usage:
  python scripts/validate_eval_set.py --embedder local
  python scripts/validate_eval_set.py --embedder local --store pgvector --table chunks_baseline
  python scripts/validate_eval_set.py --embedder local --eval-set eval/eval_set.draft.jsonl
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _cli_common import add_embedder_args, build_embedder, resolve_network_policy

from consultrag.eval import check_multi_source_coverage, load_eval_set, validate_relevant_ids
from consultrag.reranking import NoOpReranker
from consultrag.retrieval import HybridRetriever
from consultrag.vectorstore import NumpyVectorStore

ap = argparse.ArgumentParser()
ap.add_argument("--index", default="index")
ap.add_argument("--eval-set", default="eval/eval_set.jsonl")
ap.add_argument("--table", default="chunks", help="pgvector table name (--store pgvector only)")
add_embedder_args(ap)
args = ap.parse_args()
resolve_network_policy(args, ap)

embedder = build_embedder(args.embedder)
if args.store == "pgvector":
    from consultrag.pgvectorstore import PgVectorStore

    store = PgVectorStore.load(dim=embedder.dim, table_name=args.table)
else:
    store = NumpyVectorStore.load(args.index)

items = load_eval_set(args.eval_set)
known_ids = {c.chunk_id for c in store.all_chunks()}

print(f"Loaded {len(items)} questions from {args.eval_set}; {len(known_ids)} real chunk_ids in the index.\n")

id_problems = validate_relevant_ids(items, known_ids)
if id_problems:
    print(f"{len(id_problems)} relevant_id(s) do NOT match a real chunk_id:")
    for q, bad_id in id_problems:
        print(f"  BAD ID  {bad_id!r}  <- {q}")
else:
    print("All relevant_ids match real chunk_ids. OK.")

print()
retriever = HybridRetriever(store)
reranker = NoOpReranker()
coverage_problems = check_multi_source_coverage(items, embedder, retriever, reranker)
if coverage_problems:
    print(f"{len(coverage_problems)} multi-source question(s) where not all labeled chunks surfaced in top-k:")
    for p in coverage_problems:
        print(f"  Q: {p['question']}")
        print(f"     labeled:        {p['relevant_ids']}")
        print(f"     MISSING:        {p['missing']}")
        print(f"     top-k retrieved: {p['top_k_retrieved']}")
else:
    print("All multi-source questions: every labeled chunk appears in top-k. OK.")

if id_problems:
    sys.exit(1)
