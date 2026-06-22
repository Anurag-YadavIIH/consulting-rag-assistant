"""
POST /ingest — wraps the existing IngestionPipeline. Engagement and
clearance are request-declared TARGETS, validated against the authenticated
User server-side (never trusted): a caller may only ingest into an
engagement they belong to (or be a global admin), and never above their own
clearance — both checked before the pipeline is ever called.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...pipeline import IngestionPipeline
from ...security.access import AccessPolicy, User
from ..deps import get_current_app_user, get_ingestion_pipeline
from ..schemas import IngestRequest, IngestResponse

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    body: IngestRequest,
    user: User = Depends(get_current_app_user),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
) -> IngestResponse:
    is_admin = AccessPolicy.is_admin(user)
    if not is_admin and body.engagement not in AccessPolicy.engagements_for(user):
        raise HTTPException(status_code=403, detail="not a member of this engagement")
    if body.clearance > user.clearance:
        raise HTTPException(
            status_code=403, detail="cannot ingest at a clearance above your own"
        )

    n = pipeline.ingest_path(
        body.path, engagement=body.engagement, clearance=body.clearance, user_id=user.user_id
    )
    return IngestResponse(chunks_ingested=n)
