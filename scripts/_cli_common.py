"""Shared CLI helpers for ingest.py/query.py/run_eval.py.

--embedder selects the embedding backend; --store selects the vector store
backend. --offline is a network-policy switch (zero network calls, zero
model downloads) layered on top of both, so it's mutually exclusive with
anything that needs the network or a model download (a non-default
--embedder, --store pgvector, or --rerank).
"""

from __future__ import annotations

import argparse


def add_embedder_args(ap: argparse.ArgumentParser, *, include_rerank: bool = False) -> None:
    ap.add_argument(
        "--embedder",
        choices=["local", "openai", "hash"],
        default=None,
        help="local sentence-transformers (default unless --offline), "
        "openai text-embedding-3-large (opt-in, sends text off-machine), "
        "or the offline hash embedder",
    )
    ap.add_argument(
        "--store",
        choices=["numpy", "pgvector"],
        default="numpy",
        help="numpy (default, local file-based index) or pgvector "
        "(Postgres+pgvector via docker-compose; --store pgvector "
        "requires DATABASE_URL and `python scripts/migrate_pg.py` first)",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="zero network calls / zero model downloads: forces --embedder hash "
        "and --store numpy, and disables --rerank. Errors if combined with a "
        "conflicting choice.",
    )
    if include_rerank:
        ap.add_argument(
            "--rerank",
            action="store_true",
            help="cross-encoder reranking of fused candidates "
            "(downloads BAAI/bge-reranker-base on first use)",
        )


def resolve_network_policy(args: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    """Applies --offline's forced choices and rejects contradictory combinations."""
    if args.offline:
        if args.embedder not in (None, "hash"):
            ap.error(
                f"--offline forces the hash embedder; remove --embedder or set it "
                f"to hash (got --embedder {args.embedder})"
            )
        args.embedder = "hash"
        if args.store != "numpy":
            ap.error(
                f"--offline forces --store numpy (Postgres is a network call); "
                f"remove --store or set it to numpy (got --store {args.store})"
            )
        if getattr(args, "rerank", False):
            ap.error("--offline disables --rerank (it requires a model download)")
    elif args.embedder is None:
        args.embedder = "local"


def build_embedder(name: str):
    if name == "hash":
        from consultrag.embeddings import HashEmbedder

        return HashEmbedder(dim=256)
    if name == "openai":
        from consultrag.embeddings import OpenAIEmbedder

        return OpenAIEmbedder()
    from consultrag.embeddings import LocalEmbedder

    return LocalEmbedder()
