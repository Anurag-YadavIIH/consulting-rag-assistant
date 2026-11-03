#!/usr/bin/env python3
r"""LOCAL DEMO ONLY: load the fictional Meridian Health and Kestrel Medical
notes (data/demo/) into the local Docker Compose database, for screenshots
and demos.

Refuses to run if APP_ENV is production, or if DATABASE_URL points anywhere
other than localhost, 127.0.0.1 or the Compose service `postgres`. Never run
it against AWS.

Run it from the repository root on your machine, with Compose's Postgres on
localhost:5432. It uses the same embedding model as the API
(BAAI/bge-small-en-v1.5), so the vectors match. (The API image doesn't
include data/, and shouldn't, since that image also goes to AWS.)

  .venv\Scripts\python.exe scripts\seed_demo_data.py
  .venv\Scripts\python.exe scripts\seed_demo_data.py --grant-user-id 90
  docker compose restart api    # so the API's keyword index sees the new documents

--grant-user-id gives that existing user analyst membership in `meridian`
and `kestrel`, nothing else: no admin role and no clearance change. It fails,
granting nothing, for an unknown user. Documents are uploaded under their
filenames at clearance 1, so running the script again replaces them.
"""
import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEMO_DIR = ROOT / "data" / "demo"
ENGAGEMENTS = {"meridian": "Meridian Health", "kestrel": "Kestrel Medical"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "postgres"}
SEED_USER = "demo-seed"


class Refused(Exception):
    pass


def check_local(app_env: str | None, database_url: str) -> None:
    if (app_env or "").strip().lower() == "production":
        raise Refused("APP_ENV is production; this demo seed only runs locally.")
    host = urlparse(database_url).hostname
    if host not in LOCAL_HOSTS:
        raise Refused(
            f"DATABASE_URL host {host!r} isn't local ({', '.join(sorted(LOCAL_HOSTS))}); refusing."
        )


def demo_files() -> list[tuple[str, Path]]:
    return [(eng, p) for eng in ENGAGEMENTS for p in sorted((DEMO_DIR / eng).glob("*.txt"))]


def build_pipeline():
    from consultrag.audit import PgAuditLog
    from consultrag.embeddings import LocalEmbedder
    from consultrag.pgvectorstore import PgVectorStore
    from consultrag.pipeline import IngestionPipeline

    embedder = LocalEmbedder()
    store = PgVectorStore.load(dim=embedder.dim)
    return IngestionPipeline(embedder=embedder, store=store, audit=PgAuditLog(store.pool))


def build_repo():
    from consultrag.authz.repository import AuthzRepository

    return AuthzRepository()


def main(argv=None, *, app_env=None, database_url=None,
         pipeline_factory=build_pipeline, repo_factory=build_repo) -> int:
    ap = argparse.ArgumentParser(description="LOCAL DEMO ONLY: seed fictional demo engagements.")
    ap.add_argument("--grant-user-id", type=int, default=None,
                    help="existing user to make an analyst in both demo engagements")
    args = ap.parse_args(argv)

    if database_url is None:
        from consultrag.config import settings

        database_url = settings.database_url
        app_env = settings.app_env if app_env is None else app_env
    try:
        check_local(app_env if app_env is not None else os.environ.get("APP_ENV"), database_url)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2

    repo = None
    if args.grant_user_id is not None:
        repo = repo_factory()
        if not repo.user_exists(args.grant_user_id):
            repo.close()
            print(f"error: no user with id {args.grant_user_id}. Sign in once first.", file=sys.stderr)
            return 1

    pipeline = pipeline_factory()
    for engagement, path in demo_files():
        n = pipeline.ingest_path(path, engagement=engagement, clearance=1,
                                 user_id=SEED_USER, source_name=path.name)
        print(f"{ENGAGEMENTS[engagement]} ({engagement}): {path.name}, {n} chunk(s)")

    if repo is not None:
        try:
            for engagement in ENGAGEMENTS:
                repo.add_membership(args.grant_user_id, engagement, "analyst")
        finally:
            repo.close()
        print(f"user_id={args.grant_user_id}: analyst in {', '.join(ENGAGEMENTS)}. "
              "Takes effect at the next sign-in or token refresh.")
    print("Done. Restart the API (docker compose restart api) so its keyword index sees the new documents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
