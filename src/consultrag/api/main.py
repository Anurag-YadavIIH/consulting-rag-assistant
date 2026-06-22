"""
FastAPI app wrapping ConsultRAG's existing pipeline/RAG engine with
Google/OIDC authentication (auth/oidc.py) and Postgres-backed RBAC
authorization (authz/repository.py). The offline CLI (scripts/) is
untouched and keeps working independently of this module.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..auth.app_token import ensure_app_jwt_secret_configured
from ..auth.dev_bypass import ensure_dev_auth_bypass_is_safe, warn_bypass_active
from ..config import settings
from .deps import get_oidc_verifier
from .routes import auth as auth_routes
from .routes import draft as draft_routes
from .routes import ingest as ingest_routes
from .routes import me as me_routes
from .routes import query as query_routes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed: refuse to start with no/placeholder signing secret unless
    # DEV_AUTH_BYPASS is explicitly on.
    ensure_app_jwt_secret_configured(settings.app_jwt_secret, dev_auth_bypass=settings.dev_auth_bypass)

    # Fail closed AND loud: refuse to start if bypass is on without APP_ENV
    # explicitly confirming a dev environment; otherwise warn visibly once.
    ensure_dev_auth_bypass_is_safe(settings.dev_auth_bypass, settings.app_env)
    if settings.dev_auth_bypass:
        warn_bypass_active()

    # Prefetch the OIDC discovery document so the first real request doesn't
    # pay that latency. A transient failure here doesn't crash startup —
    # verify() retries lazily on first use.
    try:
        get_oidc_verifier().ensure_discovery()
    except Exception:
        logger.warning("OIDC discovery prefetch failed at startup; will retry on first request")

    yield


app = FastAPI(title="ConsultRAG API", lifespan=lifespan)

# Fail-closed by default: CORS_ALLOWED_ORIGINS is empty unless explicitly
# configured (see config.py), so no browser origin is allowed until someone
# sets it — e.g. http://localhost:3000 for local frontend/ dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(ingest_routes.router)
app.include_router(query_routes.router)
app.include_router(draft_routes.router)
app.include_router(me_routes.router)
