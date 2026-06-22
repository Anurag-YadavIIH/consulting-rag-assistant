"""
GET /me — read-only identity/authorization summary for the calling user, so
a client (the Streamlit UI, or anything else) can populate an engagement
selector from real memberships instead of a free-text box. No request body,
no mutation, no new authorization logic — reuses AccessPolicy exactly as
every other route does.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...security.access import AccessPolicy, User
from ..deps import get_current_app_user
from ..schemas import MeResponse

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_app_user)) -> MeResponse:
    return MeResponse(
        user_id=user.user_id,
        engagements=AccessPolicy.engagements_for(user),
        is_admin=AccessPolicy.is_admin(user),
        clearance=user.clearance,
    )
