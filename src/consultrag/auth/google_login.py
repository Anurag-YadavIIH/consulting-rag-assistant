"""
Composes OIDC token verification (oidc.py — WHO is this) with the Postgres
authz store (authz/repository.py — WHAT can they do) into a single
"authenticate this request" call. Kept as a plain function (not a literal
FastAPI dependency yet) so it's fully testable without a running app; the
API stage wraps this with Depends() and an OIDCError -> HTTPException(401)
translation.

At sign-in it also applies the team-access rules (authz/team.py):
ALLOWED_EMAIL_DOMAINS (refused accounts get no user row), then grants from
INITIAL_ADMIN_EMAILS and open invitations, only for a verified email.
"""

from __future__ import annotations

from ..authz.repository import AuthzRepository
from ..security.access import User
from .access_settings import email_domain, normalize_email, parse_domain_list, parse_email_list
from .oidc import OIDCError, OIDCVerifier, extract_bearer_token


class SignInRefused(Exception):
    """The account verified, but sign-in isn't allowed (ALLOWED_EMAIL_DOMAINS).
    The route answers 403 with a generic message."""


def authenticate_google_id_token(
    authorization_header: str | None,
    verifier: OIDCVerifier,
    authz_repo: AuthzRepository,
    *,
    initial_admin_emails: str | None = None,
    allowed_email_domains: str | None = None,
) -> User:
    """Raises OIDCError on any failure, SignInRefused when the domain rule
    blocks the account. On success: verifies the token, upserts the user by
    their Google `sub` (authentication), applies any sign-in grants, then
    loads CURRENT roles/clearance from Postgres (authorization) — the
    token's own claims are never used for permissions, only identity."""
    token = extract_bearer_token(authorization_header)
    claims = verifier.verify(token)
    sub = claims.get("sub")
    if not sub:
        raise OIDCError("token missing 'sub' claim")
    # The email is stored and shown as the signed-in identity, so it must be
    # one the provider has verified. Strictly the boolean true, not "true".
    email_verified = claims.get("email_verified")
    if email_verified is not True:
        raise OIDCError("token email is not verified")
    email = claims.get("email", "")
    email_norm = normalize_email(email)

    # Malformed settings raise here too (the app also refuses to start on
    # them), so a bad value can never mean "no restriction".
    initial_admins = parse_email_list(initial_admin_emails)
    allowed_domains = parse_domain_list(allowed_email_domains)

    team_conn = getattr(authz_repo, "conn", None)
    if allowed_domains and email_domain(email_norm) not in allowed_domains:
        from ..authz.team import has_invitation

        invited = team_conn is not None and has_invitation(team_conn, email_norm)
        if email_norm not in initial_admins and not invited:
            raise SignInRefused()

    user_id = authz_repo.get_or_create_user(sub, email)
    if team_conn is not None:
        from ..authz.team import apply_sign_in_grants

        apply_sign_in_grants(team_conn, user_id, email_norm, email_verified, initial_admins)
    return authz_repo.build_user(user_id)
