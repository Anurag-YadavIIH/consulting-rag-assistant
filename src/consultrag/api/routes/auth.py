"""
POST /auth/login, /auth/refresh and /auth/logout — the only routes that ever
accept a Google ID token (login) or read fresh authorization from Postgres.
Every other route uses get_current_app_user (deps.py), which trusts the
access token's own claims and never calls the database.

The refresh token lives only in an HttpOnly cookie (Secure, SameSite=Strict,
Path=/auth), never in a response body, so page scripts can't read it.
Because the browser attaches that cookie automatically, /auth/refresh and
/auth/logout also require a custom header (CSRF_HEADER). A cross-site page
can't send a custom header without a CORS preflight, which only configured
origins pass; SameSite=Strict is the second layer.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response

from ...auth.app_token import (
    DEFAULT_REFRESH_TOKEN_TTL,
    AppTokenError,
    login_with_google_id_token,
    refresh_app_token,
    revoke_with_refresh_token,
)
from ...auth.oidc import OIDCError, OIDCVerifier
from ...authz.repository import AuthzRepository
from ...config import settings
from ..deps import get_authz_repo, get_oidc_verifier
from ..schemas import LoginResponse, RefreshResponse

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "consultrag_refresh"
REFRESH_COOKIE_PATH = "/auth"
CSRF_HEADER = "X-ConsultRAG-CSRF"
CSRF_HEADER_VALUE = "1"


def _require_csrf_header(
    csrf: str | None = Header(None, alias=CSRF_HEADER),
) -> None:
    if csrf != CSRF_HEADER_VALUE:
        raise HTTPException(status_code=403, detail=f"missing {CSRF_HEADER} header")


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=DEFAULT_REFRESH_TOKEN_TTL,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, secure=True, samesite="strict"
    )


@router.post("/login", response_model=LoginResponse)
def login(
    response: Response,
    authorization: str | None = Header(None),
    verifier: OIDCVerifier = Depends(get_oidc_verifier),
    repo: AuthzRepository = Depends(get_authz_repo),
) -> LoginResponse:
    try:
        pair = login_with_google_id_token(authorization, verifier, repo, settings.app_jwt_secret)
    except OIDCError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    _set_refresh_cookie(response, pair.refresh_token)
    return LoginResponse(access_token=pair.access_token)


@router.post("/refresh", response_model=RefreshResponse,
             dependencies=[Depends(_require_csrf_header)])
def refresh(
    refresh_token: str | None = Cookie(None, alias=REFRESH_COOKIE),
    repo: AuthzRepository = Depends(get_authz_repo),
) -> RefreshResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="not signed in")
    try:
        new_access = refresh_app_token(refresh_token, settings.app_jwt_secret, repo)
    except AppTokenError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return RefreshResponse(access_token=new_access)


@router.post("/logout", status_code=204, dependencies=[Depends(_require_csrf_header)])
def logout(
    response: Response,
    refresh_token: str | None = Cookie(None, alias=REFRESH_COOKIE),
    repo: AuthzRepository = Depends(get_authz_repo),
) -> Response:
    # Revokes this user's refresh tokens on the server (all browsers), then
    # clears this browser's cookie. Always succeeds from the caller's view:
    # an invalid or already-revoked cookie is simply cleared.
    if refresh_token:
        try:
            revoke_with_refresh_token(refresh_token, settings.app_jwt_secret, repo)
        except AppTokenError:
            pass
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response
