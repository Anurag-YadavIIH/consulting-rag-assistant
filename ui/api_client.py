"""
Thin httpx wrapper around the ConsultRAG API — the ONLY place in the UI that
makes HTTP calls. ui/app.py never constructs a request itself; everything
routes through query()/ingest()/me()/get_auth_headers() below.

This module holds no business logic and never touches the DB, vector store,
or RAG engine directly — it only calls the API over HTTP. "Service + client":
the API is the service, this is the client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


class ApiError(Exception):
    """Base class for all API-call failures. Carries the HTTP status and
    server-provided detail so the UI can render something specific without
    ever showing a raw traceback."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class NotAuthenticatedError(ApiError):
    """401 — missing, malformed, or expired token."""


class ForbiddenError(ApiError):
    """403 — authenticated, but not allowed (e.g. not a member of this
    engagement, or requesting a clearance above your own)."""


class ServerError(ApiError):
    """5xx — the API itself failed."""


@dataclass
class Citation:
    source_path: str
    locator: str
    score: float
    # Future seam: `date` and `is_stale` fields will land here once the
    # live-data layer (external search, recency tagging — see
    # ARCHITECTURE.md §8) exists and /query actually returns them. Not built
    # yet on the API side, so deliberately not built here either.


@dataclass
class QueryResult:
    answer: str
    citations: list[Citation]


@dataclass
class MeInfo:
    user_id: str
    engagements: list[str]
    is_admin: bool
    clearance: int


def get_auth_headers() -> dict[str, str]:
    """The ONLY function that changes when real Google sign-in replaces
    DEV_AUTH_BYPASS. Dev bypass now (server-side — see
    src/consultrag/auth/dev_bypass.py): the API needs no token at all, so
    this returns {}. Real Google OIDC drops in HERE: exchange a stored app
    access token (obtained from POST /auth/login) for an
    'Authorization: Bearer <token>' header, refreshing via POST /auth/refresh
    as needed. Nothing else in this module, and nothing in ui/app.py, should
    assume how auth works — every call site gets its headers from this one
    function."""
    return {}


def _error_detail(resp: httpx.Response) -> str:
    try:
        return resp.json().get("detail", resp.text)
    except Exception:
        return resp.text


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        raise NotAuthenticatedError(401, _error_detail(resp))
    if resp.status_code == 403:
        raise ForbiddenError(403, _error_detail(resp))
    if resp.status_code >= 500:
        raise ServerError(resp.status_code, _error_detail(resp))
    resp.raise_for_status()


def me() -> MeInfo:
    resp = httpx.get(f"{API_BASE_URL}/me", headers=get_auth_headers(), timeout=10)
    _raise_for_status(resp)
    data = resp.json()
    return MeInfo(
        user_id=data["user_id"],
        engagements=data["engagements"],
        is_admin=data["is_admin"],
        clearance=data["clearance"],
    )


def query(question: str, engagement: str | None = None) -> QueryResult:
    resp = httpx.post(
        f"{API_BASE_URL}/query",
        json={"question": question, "engagement": engagement},
        headers=get_auth_headers(),
        timeout=60,
    )
    _raise_for_status(resp)
    data = resp.json()
    return QueryResult(
        answer=data["answer"],
        citations=[Citation(**c) for c in data["citations"]],
    )


def ingest(path: str, engagement: str, clearance: int = 1) -> int:
    resp = httpx.post(
        f"{API_BASE_URL}/ingest",
        json={"path": path, "engagement": engagement, "clearance": clearance},
        headers=get_auth_headers(),
        timeout=120,
    )
    _raise_for_status(resp)
    return resp.json()["chunks_ingested"]
