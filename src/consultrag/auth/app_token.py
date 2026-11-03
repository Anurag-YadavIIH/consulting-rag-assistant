"""
App session tokens (HS256, APP_JWT_SECRET) — issued at POST /auth/login after
Google/OIDC verification succeeds (oidc.py, google_login.py), and verified on
every other authenticated route. Deliberately a separate token type/algorithm
from the Google ID token, so the two can never be confused: this verifier
only accepts HS256 against our own secret; the OIDC verifier only accepts
RS256 against the provider's JWKS. A token of one type is, by construction,
rejected by the other's verifier — see tests/test_app_token.py.

Access vs. refresh tokens carry different `type` claims, checked explicitly.
Refresh tokens carry ONLY sub/type/iat/exp plus `ver` (the user's refresh
version) — no roles/engagements/clearance — so a refresh always re-reads
current authorization from Postgres (authz/repository.py); there is nothing
stale to carry forward even by accident. Sign-out increments the stored
version, which rejects every refresh token issued before it.

Lifetimes: access 15 minutes, refresh 7 days (fixed from login, not sliding).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt

from ..authz.repository import AuthzRepository
from ..security.access import AccessPolicy, User
from .google_login import authenticate_google_id_token
from .oidc import OIDCVerifier

ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_TTL = 900  # 15 minutes
DEFAULT_REFRESH_TOKEN_TTL = 7 * 86400  # 7 days

_PLACEHOLDER_SECRETS = {
    "",
    "changeme",
    "change-me",
    "change_me",
    "secret",
    "your-secret-here",
    "placeholder",
    "todo",
    "insecure",
    "dev-secret",
    "test-secret",
}
MIN_SECRET_LENGTH = 16


class AppTokenError(Exception):
    """An app token failed verification for any reason. Callers should treat
    this uniformly as a 401, same convention as OIDCError.

    `reason` is a coarse, safe category for server logs: "expired",
    "revoked", "invalid" or "unknown_user". It never contains the token,
    its claims or anything about the user."""

    def __init__(self, message: str, *, reason: str = "invalid"):
        super().__init__(message)
        self.reason = reason


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str


def ensure_app_jwt_secret_configured(secret: str | None, *, dev_auth_bypass: bool) -> None:
    """Refuses to start (raises RuntimeError) if APP_JWT_SECRET is unset or
    looks like a placeholder, unless dev_auth_bypass is on (Stage 5 — app
    tokens aren't the auth path at all in that mode)."""
    if dev_auth_bypass:
        return
    if (
        not secret
        or secret.strip().lower() in _PLACEHOLDER_SECRETS
        or len(secret) < MIN_SECRET_LENGTH
    ):
        raise RuntimeError(
            "APP_JWT_SECRET is unset or looks like a placeholder. Set a real "
            "random secret, e.g.:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(32))"\n'
            "or set DEV_AUTH_BYPASS=true for local-only testing."
        )


def issue_app_token(user: User, secret: str, *, expires_in: int = DEFAULT_ACCESS_TOKEN_TTL) -> str:
    now = int(time.time())
    payload = {
        "sub": user.user_id,  # internal Postgres user_id (authz.repository.build_user), NOT google_sub
        "roles": sorted(user.roles),
        "engagements": AccessPolicy.engagements_for(user),
        "clearance": user.clearance,
        "email": user.email,  # display only
        "type": "access",
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def issue_refresh_token(
    user: User, secret: str, *, version: int = 0, expires_in: int = DEFAULT_REFRESH_TOKEN_TTL
) -> str:
    now = int(time.time())
    payload = {
        "sub": user.user_id, "type": "refresh", "ver": version, "iat": now, "exp": now + expires_in,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_app_token(token: str, secret: str, *, expected_type: str = "access") -> dict:
    try:
        claims = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "iat", "sub"]}
        )
    except jwt.ExpiredSignatureError as e:
        raise AppTokenError(str(e), reason="expired") from e
    except jwt.PyJWTError as e:
        raise AppTokenError(str(e)) from e
    if claims.get("type") != expected_type:
        raise AppTokenError(f"expected a {expected_type!r} token, got {claims.get('type')!r}")
    return claims


def login_with_google_id_token(
    authorization_header: str | None,
    oidc_verifier: OIDCVerifier,
    authz_repo: AuthzRepository,
    secret: str,
) -> TokenPair:
    """POST /auth/login's logic: verify the Google ID token (Stage 2),
    upsert+load the user (Stage 1), issue a fresh token pair reflecting
    CURRENT authz."""
    user = authenticate_google_id_token(authorization_header, oidc_verifier, authz_repo)
    version = authz_repo.refresh_version(int(user.user_id))
    return TokenPair(
        access_token=issue_app_token(user, secret),
        refresh_token=issue_refresh_token(user, secret, version=version),
    )


def _refresh_token_user_id(refresh_token: str, secret: str, authz_repo: AuthzRepository) -> int:
    """Verifies a refresh token and that it hasn't been revoked; returns the
    internal user_id. Every failure, including a user that no longer exists,
    is an AppTokenError (a 401), never a 500."""
    claims = verify_app_token(refresh_token, secret, expected_type="refresh")
    try:
        user_id = int(claims["sub"])
    except ValueError as e:
        raise AppTokenError("refresh token subject is not a user id") from e
    try:
        current = authz_repo.refresh_version(user_id)
    except ValueError as e:
        raise AppTokenError(
            "refresh token does not match a known user", reason="unknown_user"
        ) from e
    if claims.get("ver") != current:
        raise AppTokenError("refresh token has been revoked", reason="revoked")
    return user_id


def refresh_app_token(refresh_token: str, secret: str, authz_repo: AuthzRepository) -> str:
    """Exchanges a valid, un-expired, un-revoked refresh token for a fresh
    access token, always re-deriving roles/clearance from
    authz/repository.py rather than trusting anything carried in the refresh
    token, so a removed role takes effect at the next refresh."""
    user_id = _refresh_token_user_id(refresh_token, secret, authz_repo)
    try:
        user = authz_repo.build_user(user_id)
    except ValueError as e:
        raise AppTokenError(
            "refresh token does not match a known user", reason="unknown_user"
        ) from e
    return issue_app_token(user, secret)


def revoke_with_refresh_token(refresh_token: str, secret: str, authz_repo: AuthzRepository) -> None:
    """Sign-out: revokes every refresh token of the user this one belongs
    to. Raises AppTokenError if the token is invalid or already revoked."""
    user_id = _refresh_token_user_id(refresh_token, secret, authz_repo)
    authz_repo.revoke_refresh_tokens(user_id)
