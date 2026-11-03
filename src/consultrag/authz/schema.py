"""
Idempotent DDL for the authorization (RBAC) store: who is this user, what
clearance do they hold, and which engagements (and roles within them) are
they a member of. This is deliberately separate from authentication
(auth/oidc.py) — a Google ID token only proves identity; this table is the
sole source of truth for what an authenticated identity is allowed to do.
"""

from __future__ import annotations


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone() is not None


def add_column_if_missing(cur, table: str, column: str, ddl: str) -> None:
    """ALTER TABLE takes an exclusive lock even with IF NOT EXISTS, so only
    run it when the column really is missing."""
    if not column_exists(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")


def ensure_authz_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                google_sub TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                clearance INT NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Refresh tokens carry the version current when they were issued;
        # sign-out increments it, so every older refresh token is rejected.
        # Added with IF NOT EXISTS so existing databases upgrade in place.
        add_column_if_missing(cur, "users", "refresh_version", "INT NOT NULL DEFAULT 0")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS engagement_memberships (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                engagement TEXT,
                role TEXT NOT NULL,
                CONSTRAINT engagement_memberships_user_engagement_role_uniq
                    UNIQUE NULLS NOT DISTINCT (user_id, engagement, role)
            )
            """
        )
        # NULLS NOT DISTINCT (pg15+; pgvector/pgvector:pg16 has it) makes two
        # (user_id, NULL, 'admin') rows collide as duplicates instead of both
        # being silently accepted — plain UNIQUE treats NULL <> NULL, which
        # would otherwise let the same global role be granted twice.
        cur.execute(
            "COMMENT ON COLUMN engagement_memberships.engagement IS "
            "'NULL engagement = global role (e.g. admin), not tied to a specific engagement'"
        )
        # Set when INITIAL_ADMIN_EMAILS granted this account admin, so it
        # happens once: a later demotion by another admin sticks.
        add_column_if_missing(cur, "users", "initial_admin_applied_at", "TIMESTAMPTZ")
        # Invitations by email, applied once at the invitee's first verified
        # sign-in. Emails live here (needed to match the sign-in), never in
        # audit_events.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS invitations (
                id BIGSERIAL PRIMARY KEY,
                email_norm TEXT NOT NULL,
                engagements TEXT[] NOT NULL DEFAULT '{}',
                role TEXT NOT NULL,
                clearance INT NOT NULL CHECK (clearance >= 1),
                is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                created_by TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at TIMESTAMPTZ NOT NULL,
                accepted_at TIMESTAMPTZ,
                accepted_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                revoked_at TIMESTAMPTZ
            )
            """
        )
        # At most one open invitation per email.
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS invitations_one_open_per_email "
            "ON invitations (email_norm) WHERE accepted_at IS NULL AND revoked_at IS NULL"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS engagement_memberships_user_id_idx "
            "ON engagement_memberships (user_id)"
        )
    conn.commit()
