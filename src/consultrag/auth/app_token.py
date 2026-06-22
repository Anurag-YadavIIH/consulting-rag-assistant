"""
App session tokens (HS256, APP_JWT_SECRET) — issued at POST /auth/login after
Google/OIDC verification succeeds (oidc.py, google_login.py), and verified on
every other authenticated route. Deliberately a separate token type/algorithm
from the Google ID token, so the two can never be confused: this verifier
only accepts HS256 against our own secret; the OIDC verifier only accepts
RS256 against the provider's JWKS. A token of one type is, by construction,
rejected by the other's verifier — see tests/test_app_token.py.

Access vs. refresh tokens carry different `type` claims, checked explicitly.
Refresh tokens carry ONLY sub/type/iat/exp — no roles/engagements/clearance —
so a refresh always re-reads current authorization from Postgres
(authz/repository.py); there is nothing stale to carry forward even by
accident.
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
    this uniformly as a 401, same convention as OIDCError."""


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
        "type": "access",
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def issue_refresh_token(user: User, secret: str, *, expires_in: int = DEFAULT_REFRESH_TOKEN_TTL) -> str:
    now = int(time.time())
    payload = {"sub": user.user_id, "type": "refresh", "iat": now, "exp": now + expires_in}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_app_token(token: str, secret: str, *, expected_type: str = "access") -> dict:
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM])
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
    return TokenPair(
        access_token=issue_app_token(user, secret),
        refresh_token=issue_refresh_token(user, secret),
    )


def refresh_app_token(refresh_token: str, secret: str, authz_repo: AuthzRepository) -> str:
    """Exchanges a valid, un-expired refresh token for a fresh access token,
    always re-deriving roles/clearance from authz/repository.py rather than
    trusting anything carried in the refresh token (which carries nothing
    but sub/type/iat/exp to begin with)."""
    claims = verify_app_token(refresh_token, secret, expected_type="refresh")
    user_id = int(claims["sub"])
    user = authz_repo.build_user(user_id)
    return issue_app_token(user, secret)
