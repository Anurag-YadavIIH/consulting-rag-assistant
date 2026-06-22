#!/usr/bin/env python3
"""Query the local index.

Usage:
  python scripts/query.py --index index --roles analyst engagement:acme \
      --clearance 2 "What is the barrier to adoption?"
  python scripts/query.py --offline "..." --roles analyst engagement:acme --clearance 2
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _cli_common import add_embedder_args, build_embedder, resolve_network_policy

from consultrag.audit import AuditLog
from consultrag.rag import RAGEngine, OllamaLLM, ExtractiveLLM
from consultrag.reranking import CrossEncoderReranker, NoOpReranker
from consultrag.security.access import User
from consultrag.vectorstore import NumpyVectorStore


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--index", default="index")
    ap.add_argument("--roles", nargs="*", default=["analyst"])
    ap.add_argument("--clearance", type=int, default=1)
    ap.add_argument("--llm", choices=["ollama", "extractive"], default="extractive")
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

    llm = OllamaLLM() if args.llm == "ollama" else ExtractiveLLM()
    engine = RAGEngine(
        embedder=embedder, store=store, llm=llm, reranker=reranker,
        audit=AuditLog(Path(args.index) / "audit.log"),
    )
    user = User.make("cli-user", roles=args.roles, clearance=args.clearance)
    ans = engine.answer(args.question, user)

    print("\n=== ANSWER ===\n" + ans.text)
    print("\n=== SOURCES ===")
    for c in ans.citations:
        print(f"  - {c.source_path} [{c.locator}]  (score {c.score:.3f})")


if __name__ == "__main__":
    main()
