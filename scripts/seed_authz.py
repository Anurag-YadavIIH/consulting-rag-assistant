#!/usr/bin/env python3
"""Seed a local user (and optional engagement membership / global admin role)
for manual API testing.

Usage:
  python scripts/seed_authz.py --google-sub admin-sub-123 --email admin@example.com --admin
  python scripts/seed_authz.py --google-sub analyst-sub-456 --email analyst@example.com \
      --engagement acme --role analyst --clearance 2
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.authz.repository import AuthzRepository


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--google-sub", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--clearance", type=int, default=1)
    ap.add_argument("--engagement", default=None, help="grant membership in this engagement")
    ap.add_argument("--role", default="analyst")
    ap.add_argument("--admin", action="store_true", help="grant the global admin role")
    args = ap.parse_args()

    repo = AuthzRepository()
    user_id = repo.get_or_create_user(args.google_sub, args.email)
    repo.set_clearance(user_id, args.clearance)
    if args.engagement:
        repo.add_membership(user_id, args.engagement, args.role)
    if args.admin:
        repo.add_membership(user_id, None, "admin")
    repo.close()
    print(
        f"Seeded user_id={user_id} (google_sub={args.google_sub}, email={args.email}, "
        f"clearance={args.clearance})"
    )


if __name__ == "__main__":
    main()
