"""
Repository over the authz schema (schema.py). Two call sites matter most:
- API auth flow (Stage 2/3): get_or_create_user() at login, build_user() on
  every authenticated request to load CURRENT roles/clearance from Postgres
  (never trust stale claims for authorization — only for identity).
- scripts/seed_authz.py: add_membership()/set_clearance() for local setup.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..security.access import User
from .schema import ensure_authz_schema


@dataclass
class AuthzInfo:
    roles: frozenset[str]
    engagements: list[str]
    clearance: int


class AuthzRepository:
    def __init__(self, dsn: str | None = None):
        import psycopg

        from ..config import settings

        self._conn = psycopg.connect(dsn or settings.database_url, autocommit=False)
        ensure_authz_schema(self._conn)

    def get_or_create_user(self, google_sub: str, email: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (google_sub, email)
                VALUES (%(google_sub)s, %(email)s)
                ON CONFLICT (google_sub) DO UPDATE SET email = EXCLUDED.email
                RETURNING id
                """,
                {"google_sub": google_sub, "email": email},
            )
            user_id = cur.fetchone()[0]
        self._conn.commit()
        return user_id

    def get_user_authz(self, user_id: int) -> AuthzInfo:
        with self._conn.cursor() as cur:
            cur.execute("SELECT clearance FROM users WHERE id = %(id)s", {"id": user_id})
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"no such user_id: {user_id}")
            clearance = row[0]

            cur.execute(
                "SELECT engagement, role FROM engagement_memberships WHERE user_id = %(id)s",
                {"id": user_id},
            )
            memberships = cur.fetchall()

        roles: set[str] = set()
        engagements: list[str] = []
        for engagement, role in memberships:
            if engagement is None:
                roles.add(role)  # global grant, e.g. "admin"
            else:
                roles.add(f"engagement:{engagement}")
                roles.add(role)
                engagements.append(engagement)

        return AuthzInfo(roles=frozenset(roles), engagements=engagements, clearance=clearance)

    def build_user(self, user_id: int) -> User:
        info = self.get_user_authz(user_id)
        return User(user_id=str(user_id), roles=info.roles, clearance=info.clearance)

    def add_membership(self, user_id: int, engagement: str | None, role: str) -> None:
        """engagement=None grants a global role (e.g. add_membership(uid, None, "admin"))."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO engagement_memberships (user_id, engagement, role)
                VALUES (%(user_id)s, %(engagement)s, %(role)s)
                ON CONFLICT ON CONSTRAINT engagement_memberships_user_engagement_role_uniq
                    DO NOTHING
                """,
                {"user_id": user_id, "engagement": engagement, "role": role},
            )
        self._conn.commit()

    def set_clearance(self, user_id: int, clearance: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET clearance = %(clearance)s WHERE id = %(id)s",
                {"clearance": clearance, "id": user_id},
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
