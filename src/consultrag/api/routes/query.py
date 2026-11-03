"""
POST /query — wraps the existing RAGEngine. If `engagement` is given, it's
validated as membership the caller actually holds (403, with NO body other
than the error detail, if not) before the RAG engine is ever called — no
chunk content, counts, or metadata leak for a forbidden engagement. It
then limits retrieval and citations to that one engagement (in the SQL
query, the keyword search and before reranking). Whether or not `engagement`
is given, retrieval itself is always scoped to the caller's actual
memberships by RAGEngine's existing AccessPolicy filter (plus a SQL-level
filter too, when the store supports it); `engagement` only narrows that.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...rag import RAGEngine
from ...security.access import AccessPolicy, User
from ..deps import get_current_app_user, get_rag_engine
from ..schemas import CitationResponse, QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


NO_ACCESS_DETAIL = (
    "no access yet: your account isn't a member of any engagement. "
    "Ask an administrator to grant you access."
)


def _require_some_access(user: User) -> None:
    # A signed-in account with no engagement and no admin role (e.g. a Google
    # account that has never been granted anything) can't query at all, so it
    # can't reach chunks that have no engagement either.
    if not AccessPolicy.is_admin(user) and not AccessPolicy.engagements_for(user):
        raise HTTPException(status_code=403, detail=NO_ACCESS_DETAIL)


def _require_engagement_membership(user: User, engagement: str | None) -> None:
    if engagement is None:
        return
    if not AccessPolicy.is_admin(user) and engagement not in AccessPolicy.engagements_for(user):
        raise HTTPException(status_code=403, detail="not a member of this engagement")


@router.post("/query", response_model=QueryResponse)
def query(
    body: QueryRequest,
    user: User = Depends(get_current_app_user),
    engine: RAGEngine = Depends(get_rag_engine),
) -> QueryResponse:
    _require_some_access(user)
    _require_engagement_membership(user, body.engagement)

    answer = engine.answer(body.question, user, engagement=body.engagement)
    return QueryResponse(
        answer=answer.text,
        citations=[
            CitationResponse(
                number=c.number, source_path=c.source_path, locator=c.locator,
                score=c.score, text=c.text,
            )
            for c in answer.citations
        ],
    )
