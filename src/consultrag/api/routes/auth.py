"""
POST /auth/login and POST /auth/refresh — the only two routes that ever
accept a Google ID token (login) or read fresh authorization from Postgres
(both). Every other route uses get_current_app_user (deps.py), which trusts
the access token's own claims and never calls the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from ...auth.app_token import AppTokenError, login_with_google_id_token, refresh_app_token
from ...auth.oidc import OIDCError, OIDCVerifier
from ...authz.repository import AuthzRepository
from ...config import settings
from ..deps import get_authz_repo, get_oidc_verifier
from ..schemas import LoginResponse, RefreshRequest, RefreshResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    authorization: str | None = Header(None),
    verifier: OIDCVerifier = Depends(get_oidc_verifier),
    repo: AuthzRepository = Depends(get_authz_repo),
) -> LoginResponse:
    try:
        pair = login_with_google_id_token(authorization, verifier, repo, settings.app_jwt_secret)
    except OIDCError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return LoginResponse(access_token=pair.access_token, refresh_token=pair.refresh_token)


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    body: RefreshRequest,
    repo: AuthzRepository = Depends(get_authz_repo),
) -> RefreshResponse:
    try:
        new_access = refresh_app_token(body.refresh_token, settings.app_jwt_secret, repo)
    except AppTokenError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return RefreshResponse(access_token=new_access)
