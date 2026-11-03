"""
GET /documents and DELETE /documents: list and delete the documents of one
engagement.

Access is the same as /query: a signed-in account with no access gets 403
"no access yet", and a caller who isn't a member of the engagement (and isn't
an admin) gets 403.

Hidden documents: a document with any chunk above the caller's clearance is
one they couldn't retrieve, so the list leaves it out entirely (it can't
affect the counts shown), and DELETE answers it with exactly the same 404 as
a document that doesn't exist.

Who may delete: the same rule as replacing a document by uploading the same
name (routes/ingest.py). A member may delete a document when none of its
chunks is above their clearance; admins always can. Anyone allowed to replace
a document can already overwrite all of its content, so deletion grants
nothing beyond that.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...pipeline import IngestionPipeline
from ...rag import RAGEngine
from ...security.access import AccessPolicy, User
from ...vectorstore import DocumentReplaceForbidden
from ..deps import get_current_app_user, get_ingestion_pipeline, get_rag_engine
from ..schemas import DeleteDocumentResponse, DocumentInfo, DocumentsResponse
from .ingest import _refresh_keyword_index
from .query import _require_engagement_membership, _require_some_access

router = APIRouter(tags=["documents"])

NOT_FOUND_DETAIL = "no such document in this engagement"


@router.get("/documents", response_model=DocumentsResponse)
def list_documents(
    engagement: str = Query(..., min_length=1),
    user: User = Depends(get_current_app_user),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
) -> DocumentsResponse:
    _require_some_access(user)
    _require_engagement_membership(user, engagement)
    docs = pipeline.store.list_documents(engagement, max_clearance=user.clearance)
    return DocumentsResponse(
        engagement=engagement, documents=[DocumentInfo(**d) for d in docs]
    )


@router.delete("/documents", response_model=DeleteDocumentResponse)
def delete_document(
    engagement: str = Query(..., min_length=1),
    name: str = Query(..., min_length=1, max_length=255),
    user: User = Depends(get_current_app_user),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    engine: RAGEngine = Depends(get_rag_engine),
) -> DeleteDocumentResponse:
    _require_some_access(user)
    _require_engagement_membership(user, engagement)
    try:
        n = pipeline.delete_document(
            engagement, name, user_id=user.user_id,
            max_existing_clearance=None if AccessPolicy.is_admin(user) else user.clearance,
        )
    except DocumentReplaceForbidden:
        n = 0  # hidden from this caller: answered exactly like a missing document
    if n == 0:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    # Dense search reads the store directly; the keyword index is a snapshot
    # and must be refreshed (in this process only, as after an upload).
    _refresh_keyword_index(engine)
    return DeleteDocumentResponse(name=name, chunks_deleted=n)
