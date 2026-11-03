"""
GET /admin/activity: recent ingest, delete and query activity from the
audit_events table, newest first, for global admins only (403 otherwise,
checked here on the server).

The table holds no question text, chunk text, document content or emails
(see audit.py), so everything it has can be shown. Users appear by their
internal user ID only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...security.access import AccessPolicy, User
from ..deps import get_audit_log, get_current_app_user
from ..schemas import ActivityEvent, ActivityResponse

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_PAGE = 200


def _require_admin(user: User = Depends(get_current_app_user)) -> User:
    if not AccessPolicy.is_admin(user):
        raise HTTPException(status_code=403, detail="admins only")
    return user


@router.get("/activity", response_model=ActivityResponse)
def activity(
    limit: int = Query(50, ge=1, le=MAX_PAGE),
    before: int | None = Query(None, ge=1),
    _: User = Depends(_require_admin),
    audit=Depends(get_audit_log),
) -> ActivityResponse:
    # One extra row tells us whether an older page exists.
    rows = audit.recent(limit=limit + 1, before=before)
    page, more = rows[:limit], len(rows) > limit
    return ActivityResponse(
        events=[ActivityEvent(**r) for r in page],
        next_before=page[-1]["id"] if more and page else None,
    )
