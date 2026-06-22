"""Request/response models. None of these carry engagement/clearance as an
*authorization* input — every route derives that from the authenticated
User (see deps.py:get_current_app_user), never from these bodies. Where a
body has an `engagement` field (ingest, query, draft), it's a declared
*target* that gets validated against the caller's actual memberships, never
trusted to grant access on its own."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class MeResponse(BaseModel):
    user_id: str
    engagements: list[str]
    is_admin: bool
    clearance: int


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class IngestRequest(BaseModel):
    path: str
    engagement: str
    clearance: int = 1


class IngestResponse(BaseModel):
    chunks_ingested: int


class QueryRequest(BaseModel):
    question: str
    engagement: str | None = None
    llm: Literal["extractive", "ollama"] = "extractive"


class CitationResponse(BaseModel):
    source_path: str
    locator: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]


class DraftRequest(BaseModel):
    topic: str
    engagement: str | None = None


class DraftResponse(BaseModel):
    draft: str
    citations: list[CitationResponse]
