"""
POST /draft — same engine and isolation rules as /query, framed as drafting
a deliverable section rather than answering a question directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...rag import RAGEngine
from ...security.access import User
from ..deps import get_current_app_user, get_rag_engine
from ..schemas import CitationResponse, DraftRequest, DraftResponse
from .query import _require_engagement_membership

router = APIRouter(tags=["draft"])

DRAFT_SYSTEM_PROMPT = (
    "You are drafting a deliverable section for a management consulting client. "
    "Write in a polished, structured memo style using ONLY the provided context. "
    "Cite the source file and locator for each claim. If the context is "
    "insufficient for a confident draft, say so plainly. Never invent figures."
)


@router.post("/draft", response_model=DraftResponse)
def draft(
    body: DraftRequest,
    user: User = Depends(get_current_app_user),
    engine: RAGEngine = Depends(get_rag_engine),
) -> DraftResponse:
    _require_engagement_membership(user, body.engagement)

    answer = engine.answer(body.topic, user, system_prompt=DRAFT_SYSTEM_PROMPT)
    return DraftResponse(
        draft=answer.text,
        citations=[
            CitationResponse(source_path=c.source_path, locator=c.locator, score=c.score)
            for c in answer.citations
        ],
    )
