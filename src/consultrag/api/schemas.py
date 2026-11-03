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
    email: str = ""


class LoginResponse(BaseModel):
    # The refresh token is deliberately NOT in the body: it's set as an
    # HttpOnly cookie (routes/auth.py) so page scripts can never read it.
    access_token: str
    token_type: str = "bearer"


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class IngestRequest(BaseModel):
    path: str
    engagement: str
    clearance: int = 1


class IngestResponse(BaseModel):
    chunks_ingested: int


class UploadResponse(IngestResponse):
    # The cleaned filename the document is stored and cited under.
    source_name: str


class QueryRequest(BaseModel):
    question: str
    engagement: str | None = None
    llm: Literal["extractive", "ollama"] = "extractive"


class CitationResponse(BaseModel):
    # Matches the [n] of the passage in the answer's context. Clickable [n]
    # in the answer text is only guaranteed in extractive mode; clients must
    # show the source list even when the answer has no numbers.
    number: int
    source_path: str
    locator: str
    score: float
    # Redacted passage text from a chunk the caller is allowed to see.
    text: str
    # "similarity" (dense cosine, 0 to 1), "keyword" (raw BM25, a different
    # unbounded scale) or "other". Scores are not confidences.
    score_kind: str = "other"


class QuoteResponse(BaseModel):
    number: int
    # Redacted passage text, the same as citation `number`'s text.
    text: str


class QueryResponse(BaseModel):
    # Plain-text answer, unchanged (the CLI and older clients use it).
    answer: str
    citations: list[CitationResponse]
    # "extractive": `quotes` lists the passages the answer quotes, by
    # citation number, so a client can show them without parsing `answer`.
    # "generative": `quotes` is empty and `answer` is the model's text.
    mode: str = "extractive"
    quotes: list[QuoteResponse] = []


class DocumentInfo(BaseModel):
    name: str
    chunks: int
    clearance: int
    # UTC ISO 8601; null for documents ingested before upload times were kept.
    uploaded_at: str | None = None


class DocumentsResponse(BaseModel):
    engagement: str
    documents: list[DocumentInfo]


class DeleteDocumentResponse(BaseModel):
    name: str
    chunks_deleted: int


class ActivityEvent(BaseModel):
    id: int
    ts: str
    event: str
    user_id: str
    engagement: str | None = None
    document: str | None = None
    n_chunks: int | None = None
    redaction_counts: dict | None = None
    n_retrieved: int | None = None
    n_blocked: int | None = None
    # Access changes only: what changed, for which user or invitation (IDs,
    # never emails), and the clearance involved.
    action: str | None = None
    target_user_id: str | None = None
    invitation_id: int | None = None
    clearance: int | None = None


class ActivityResponse(BaseModel):
    events: list[ActivityEvent]
    # Pass as `before` to get the next (older) page; null when there's no more.
    next_before: int | None = None


class DraftRequest(BaseModel):
    topic: str
    engagement: str | None = None


class DraftResponse(BaseModel):
    draft: str
    citations: list[CitationResponse]
    mode: str = "extractive"
    quotes: list[QuoteResponse] = []


# --- team access (routes/team.py) -------------------------------------------------

TeamRole = Literal["analyst", "manager", "senior_management", "admin"]
EngagementRole = Literal["analyst", "manager", "senior_management"]


class EngagementMembership(BaseModel):
    engagement: str
    role: EngagementRole = "analyst"


class MemberInfo(BaseModel):
    user_id: str
    # Shown to admins on the Team page only; never written to audit_events.
    email: str
    clearance: int
    is_admin: bool
    engagements: list[EngagementMembership]
    # A label derived from admin and clearance (analyst, manager,
    # senior_management, admin or custom); presets grant nothing themselves.
    preset: str
    has_access: bool


class MembersResponse(BaseModel):
    members: list[MemberInfo]


class MemberUpdate(BaseModel):
    clearance: int | None = None
    is_admin: bool | None = None
    # Replaces the member's engagement memberships when given.
    engagements: list[EngagementMembership] | None = None


class InviteRequest(BaseModel):
    email: str
    engagements: list[str] = []
    role: TeamRole = "analyst"
    clearance: int = 1
    is_admin: bool = False


class InvitationInfo(BaseModel):
    id: int
    email: str
    engagements: list[str]
    role: str
    clearance: int
    is_admin: bool
    created_at: str
    expires_at: str


class InvitationsResponse(BaseModel):
    invitations: list[InvitationInfo]


class EngagementsResponse(BaseModel):
    engagements: list[str]

