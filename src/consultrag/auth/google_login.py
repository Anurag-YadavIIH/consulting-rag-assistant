"""
Composes OIDC token verification (oidc.py — WHO is this) with the Postgres
authz store (authz/repository.py — WHAT can they do) into a single
"authenticate this request" call. Kept as a plain function (not a literal
FastAPI dependency yet) so it's fully testable without a running app; the
API stage wraps this with Depends() and an OIDCError -> HTTPException(401)
translation.
"""

from __future__ import annotations

from ..authz.repository import AuthzRepository
from ..security.access import User
from .oidc import OIDCError, OIDCVerifier, extract_bearer_token


def authenticate_google_id_token(
    authorization_header: str | None,
    verifier: OIDCVerifier,
    authz_repo: AuthzRepository,
) -> User:
    """Raises OIDCError on any failure. On success: verifies the token,
    upserts the user by their Google `sub` (authentication), then loads
    CURRENT roles/clearance from Postgres (authorization) — the token's own
    claims are never used for permissions, only identity."""
    token = extract_bearer_token(authorization_header)
    claims = verifier.verify(token)
    sub = claims.get("sub")
    if not sub:
        raise OIDCError("token missing 'sub' claim")
    email = claims.get("email", "")
    user_id = authz_repo.get_or_create_user(sub, email)
    return authz_repo.build_user(user_id)
