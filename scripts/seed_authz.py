#!/usr/bin/env python3
"""Seed a local user (and optional engagement membership / global admin role)
for manual API testing.

Usage:
  # Create or update a user by Google subject ID:
  python scripts/seed_authz.py --google-sub admin-sub-123 --email admin@example.com --admin
  python scripts/seed_authz.py --google-sub analyst-sub-456 --email analyst@example.com \
      --engagement acme --role analyst --clearance 2

  # Grant access to an account that has already signed in, by the internal
  # user number shown in the frontend sidebar. Needs no email or Google
  # subject ID, changes nothing that isn't asked for, and fails for an
  # unknown number:
  python scripts/seed_authz.py --user-id 3 --engagement acme --role analyst

The output never includes emails or Google subject IDs.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.authz.repository import AuthzRepository
from consultrag.security.access import MAX_CLEARANCE, MIN_CLEARANCE


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--google-sub", help="create or update the user with this Google subject ID")
    who.add_argument("--user-id", type=int, help="an existing user's internal number")
    ap.add_argument("--email", help="required with --google-sub")
    ap.add_argument("--clearance", type=int, default=None,
                    help="set clearance (with --google-sub, defaults to 1)")
    ap.add_argument("--engagement", default=None, help="grant membership in this engagement")
    ap.add_argument("--role", default="analyst")
    ap.add_argument("--admin", action="store_true", help="grant the global admin role")
    return ap


def main(argv=None, repo_factory=AuthzRepository) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.google_sub and not args.email:
        ap.error("--email is required with --google-sub")
    if args.user_id is not None and not (args.engagement or args.admin or args.clearance is not None):
        ap.error("--user-id grants nothing by default: pass --engagement, --admin and/or --clearance")
    if args.clearance is not None and not (MIN_CLEARANCE <= args.clearance <= MAX_CLEARANCE):
        ap.error(f"--clearance must be {MIN_CLEARANCE} to {MAX_CLEARANCE}")
    if args.engagement and args.role == "admin":
        # Admin is a global role only: an engagement row labelled "admin"
        # grants no admin rights (authz/repository.py). Use --admin for that.
        ap.error("--role admin isn't allowed with --engagement; use --admin to grant global admin")

    repo = repo_factory()
    try:
        if args.user_id is not None:
            if not repo.user_exists(args.user_id):
                print(f"error: no user with id {args.user_id}. Sign in once first.", file=sys.stderr)
                return 1
            user_id = args.user_id
            if args.clearance is not None:
                repo.set_clearance(user_id, args.clearance)
        else:
            user_id = repo.get_or_create_user(args.google_sub, args.email)
            repo.set_clearance(user_id, args.clearance if args.clearance is not None else 1)
        granted = []
        if args.engagement:
            repo.add_membership(user_id, args.engagement, args.role)
            granted.append(f"{args.role} in {args.engagement}")
        if args.admin:
            repo.add_membership(user_id, None, "admin")
            granted.append("global admin")
        if args.clearance is not None or args.user_id is None:
            granted.append(f"clearance {args.clearance if args.clearance is not None else 1}")
    finally:
        repo.close()
    print(f"Seeded user_id={user_id}: {', '.join(granted)}. "
          "Takes effect at the user's next sign-in or token refresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
