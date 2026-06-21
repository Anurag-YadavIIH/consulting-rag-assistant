#!/usr/bin/env python3
"""Create/verify the Postgres+pgvector schema used by PgVectorStore.

Usage:
  python scripts/migrate_pg.py --dim 384
  python scripts/migrate_pg.py --dim 3072 --table chunks_openai
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.config import settings
from consultrag.pgvectorstore import ensure_schema


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dim", type=int, required=True,
        help="embedding dimension to provision (384 for local, 256 for hash, "
        "3072 for openai text-embedding-3-large)",
    )
    ap.add_argument("--table", default="chunks")
    ap.add_argument("--dsn", default=None, help="defaults to DATABASE_URL from .env")
    args = ap.parse_args()

    import psycopg

    dsn = args.dsn or settings.database_url
    conn = psycopg.connect(dsn)
    try:
        ensure_schema(conn, args.dim, args.table)
        print(f"Schema ready: table '{args.table}' (dim={args.dim}) at {dsn}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
