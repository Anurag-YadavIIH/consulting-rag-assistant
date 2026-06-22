#!/usr/bin/env python3
"""Create/verify the Postgres schema for authorization (users + engagement_memberships).

Usage:
  python scripts/migrate_authz.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.authz.schema import ensure_authz_schema
from consultrag.config import settings


def main():
    import psycopg

    conn = psycopg.connect(settings.database_url)
    try:
        ensure_authz_schema(conn)
        print(f"Authz schema ready at {settings.database_url}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
