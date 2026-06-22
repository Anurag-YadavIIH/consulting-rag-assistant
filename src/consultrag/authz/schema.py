"""
Idempotent DDL for the authorization (RBAC) store: who is this user, what
clearance do they hold, and which engagements (and roles within them) are
they a member of. This is deliberately separate from authentication
(auth/oidc.py) — a Google ID token only proves identity; this table is the
sole source of truth for what an authenticated identity is allowed to do.
"""

from __future__ import annotations


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
        cur.execute(
            "CREATE INDEX IF NOT EXISTS engagement_memberships_user_id_idx "
            "ON engagement_memberships (user_id)"
        )
    conn.commit()
