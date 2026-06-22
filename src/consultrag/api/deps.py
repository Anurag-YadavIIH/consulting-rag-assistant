"""
FastAPI dependencies. Two different concerns live here, kept deliberately
separate:

  * Authentication (get_current_app_user, get_oidc_verifier) — WHO is this.
    get_current_app_user builds a User entirely from the verified access
    token's own claims (roles/engagements/clearance), with NO database call
    on the request path — Stage 3 designed the token that way specifically
    so protected routes don't pay a DB round-trip per request. The Postgres
    authz store (authz/repository.py) is only consulted at /auth/login and
    /auth/refresh, where CURRENT permissions are re-derived.

  * Plumbing (get_authz_repo, get_rag_engine, get_ingestion_pipeline) — the
    engine/pipeline/repo instances routes need. Tests override every one of
    these via FastAPI's dependency_overrides, which is what keeps most of
    the test suite free of any real Postgres or model-download dependency.

Authorization decisions (what a request may do) are NOT made here — they
live in the route handlers, using AccessPolicy + the User this module
produces. This module never reads engagement/clearance from a request body.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from ..auth.app_token import AppTokenError, verify_app_token
from ..auth.dev_bypass import DEV_USER
from ..auth.oidc import OIDCError, OIDCVerifier, extract_bearer_token
from ..authz.repository import AuthzRepository
from ..config import settings
from ..embeddings import LocalEmbedder
from ..pipeline import IngestionPipeline
from ..rag import RAGEngine
from ..security.access import User

_verifier: OIDCVerifier | None = None
_embedder = None
_engine: RAGEngine | None = None
_pipeline: IngestionPipeline | None = None


def get_oidc_verifier() -> OIDCVerifier:
    global _verifier
    if _verifier is None:
        _verifier = OIDCVerifier(
            discovery_url=settings.oauth_discovery_url, audience=settings.oauth_audience
        )
    return _verifier


def get_authz_repo() -> AuthzRepository:
    return AuthzRepository()


def get_current_app_user(authorization: str | None = Header(None)) -> User:
    """Verifies the access token and builds a User from ITS claims only —
    no DB call here. A Google ID token presented here fails verify_app_token
    (wrong algorithm; see auth/app_token.py's docstring) and is rejected the
    same as any other invalid token: 401.

    If DEV_AUTH_BYPASS is on, returns a fixed dev User unconditionally,
    without even looking at the Authorization header — safe to reach this
    branch only because main.py's lifespan already refused to start unless
    APP_ENV explicitly confirmed a dev environment (auth/dev_bypass.py)."""
    if settings.dev_auth_bypass:
        return DEV_USER
    try:
        token = extract_bearer_token(authorization)
        claims = verify_app_token(token, settings.app_jwt_secret, expected_type="access")
    except (OIDCError, AppTokenError) as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return User(
        user_id=claims["sub"], roles=frozenset(claims["roles"]), clearance=claims["clearance"]
    )


def get_rag_engine() -> RAGEngine:
    global _embedder, _engine
    if _engine is None:
        from ..pgvectorstore import PgVectorStore

        if _embedder is None:
            _embedder = LocalEmbedder()
        store = PgVectorStore.load(dim=_embedder.dim)
        _engine = RAGEngine(embedder=_embedder, store=store)
    return _engine


def get_ingestion_pipeline() -> IngestionPipeline:
    global _embedder, _pipeline
    if _pipeline is None:
        from ..pgvectorstore import PgVectorStore

        if _embedder is None:
            _embedder = LocalEmbedder()
        store = PgVectorStore.load(dim=_embedder.dim)
        _pipeline = IngestionPipeline(embedder=_embedder, store=store)
    return _pipeline
