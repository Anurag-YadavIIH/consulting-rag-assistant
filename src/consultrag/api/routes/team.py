"""
Team access management for the Team page, all under /admin and all
admin-only. Every route requires the admin role in the access token AND
re-checks admin in Postgres, so a demoted admin loses these routes at once
rather than when their token expires.

  GET    /admin/members                list users, their access and preset
  PATCH  /admin/members/{user_id}      change clearance, admin, engagements
  DELETE /admin/members/{user_id}      remove all access, revoke refresh tokens
  GET    /admin/invitations            open invitations
  POST   /admin/invitations            invite an email (no email is sent)
  DELETE /admin/invitations/{id}       revoke an open invitation
  GET    /admin/engagements            engagement names for the invite form

Rules live in authz/team.py: presets over engagement and clearance, last
admin and self-lockout protection, audit rows without emails. Changes reach
a user at their next token refresh; an access token already issued can last
up to 15 minutes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...authz import team
from ...authz.repository import AuthzRepository
from ...config import settings
from ...security.access import AccessPolicy, User
from ..deps import get_authz_repo, get_current_app_user
from ..schemas import (
    EngagementsResponse,
    InvitationInfo,
    InvitationsResponse,
    InviteRequest,
    MemberInfo,
    MembersResponse,
    MemberUpdate,
)

router = APIRouter(prefix="/admin", tags=["team"])


def _require_team_admin(
    user: User = Depends(get_current_app_user),
    repo: AuthzRepository = Depends(get_authz_repo),
) -> tuple[User, AuthzRepository]:
    if not AccessPolicy.is_admin(user) or not team.is_admin_in_db(repo.conn, user.user_id):
        raise HTTPException(status_code=403, detail="admins only")
    return user, repo


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except team.TeamError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None


@router.get("/members", response_model=MembersResponse)
def list_members(ctx=Depends(_require_team_admin)) -> MembersResponse:
    _, repo = ctx
    return MembersResponse(members=[MemberInfo(**m) for m in team.list_members(repo.conn)])


@router.patch("/members/{user_id}", response_model=MembersResponse)
def update_member(user_id: int, body: MemberUpdate, ctx=Depends(_require_team_admin)) -> MembersResponse:
    actor, repo = ctx
    _run(
        team.update_member, repo.conn, actor.user_id, user_id,
        clearance=body.clearance, is_admin=body.is_admin,
        engagements=[e.model_dump() for e in body.engagements] if body.engagements is not None else None,
    )
    return MembersResponse(members=[MemberInfo(**m) for m in team.list_members(repo.conn)])


@router.delete("/members/{user_id}", response_model=MembersResponse)
def remove_member(user_id: int, ctx=Depends(_require_team_admin)) -> MembersResponse:
    actor, repo = ctx
    _run(team.remove_member, repo.conn, actor.user_id, user_id)
    return MembersResponse(members=[MemberInfo(**m) for m in team.list_members(repo.conn)])


@router.get("/invitations", response_model=InvitationsResponse)
def list_invitations(ctx=Depends(_require_team_admin)) -> InvitationsResponse:
    _, repo = ctx
    return InvitationsResponse(invitations=[InvitationInfo(**i) for i in team.list_invitations(repo.conn)])


@router.post("/invitations", response_model=InvitationInfo, status_code=201)
def create_invitation(body: InviteRequest, ctx=Depends(_require_team_admin)) -> InvitationInfo:
    actor, repo = ctx
    spec = team.InviteSpec(
        email=body.email, engagements=body.engagements, role=body.role,
        clearance=body.clearance, is_admin=body.is_admin,
    )
    return InvitationInfo(**_run(team.create_invitation, repo.conn, actor.user_id, spec, settings.invitation_ttl_days))


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke_invitation(invitation_id: int, ctx=Depends(_require_team_admin)) -> None:
    actor, repo = ctx
    _run(team.revoke_invitation, repo.conn, actor.user_id, invitation_id)


@router.get("/engagements", response_model=EngagementsResponse)
def list_engagements(ctx=Depends(_require_team_admin)) -> EngagementsResponse:
    _, repo = ctx
    return EngagementsResponse(engagements=team.list_engagements(repo.conn))
