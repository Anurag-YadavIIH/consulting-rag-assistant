#!/usr/bin/env python3
"""Ingest files or a folder into the local index.

Usage:
  python scripts/ingest.py --path data/sample --engagement acme --clearance 2
  python scripts/ingest.py --path data/sample --offline   # zero network calls / downloads
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _cli_common import add_embedder_args, build_embedder, resolve_network_policy

from consultrag.audit import AuditLog
from consultrag.pipeline import IngestionPipeline
from consultrag.vectorstore import NumpyVectorStore


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="file or directory to ingest")
    ap.add_argument("--index", default="index", help="index directory")
    ap.add_argument("--engagement", default=None)
    ap.add_argument("--clearance", type=int, default=1)
    ap.add_argument("--table", default="chunks", help="pgvector table name (--store pgvector only)")
    add_embedder_args(ap)
    args = ap.parse_args()
    resolve_network_policy(args, ap)

    embedder = build_embedder(args.embedder)
    index_dir = Path(args.index)

    if args.store == "pgvector":
        from consultrag.pgvectorstore import PgVectorStore

        store = PgVectorStore.load(dim=embedder.dim, table_name=args.table)
        audit_path = index_dir / "audit.log"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        if (index_dir / "meta.json").exists():
            store = NumpyVectorStore.load(index_dir)
        else:
            store = NumpyVectorStore(dim=embedder.dim)
        audit_path = index_dir / "audit.log"

    pipe = IngestionPipeline(
        embedder=embedder,
        store=store,
        audit=AuditLog(audit_path),
    )
    n = pipe.ingest_path(
        args.path, engagement=args.engagement, clearance=args.clearance
    )

    if args.store == "pgvector":
        print(f"Ingested {n} chunks. Index now holds {len(store)} chunks in Postgres "
              f"(table '{store.table_name}')")
    else:
        store.save(index_dir)
        print(f"Ingested {n} chunks. Index now holds {len(store)} chunks at {index_dir}/")


if __name__ == "__main__":
    main()
