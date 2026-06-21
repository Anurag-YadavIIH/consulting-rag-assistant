"""
Role-based access control (RBAC).

Every chunk carries metadata: which client engagement it belongs to and the
minimum clearance needed to see it. At query time we filter retrieved chunks by
the requesting user's roles BEFORE they reach the LLM, so one analyst can't pull
another client's confidential material through the assistant.

This is deliberately simple and in-process. In a real deployment you'd back it
with your identity provider (SSO/OIDC) and enforce filters at the vector-store
query layer too. The point for the project is to show you designed for tenant
isolation rather than dumping everything into one searchable pool.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class User:
    user_id: str
    roles: frozenset[str]          # e.g. {"analyst", "engagement:acme"}
    clearance: int = 1             # 1 = standard, higher = more sensitive

    @staticmethod
    def make(user_id: str, roles: list[str], clearance: int = 1) -> "User":
        return User(user_id=user_id, roles=frozenset(roles), clearance=clearance)


@dataclass
class AccessPolicy:
    """Decides whether a user may read a chunk given the chunk's metadata."""

    def can_read(self, user: User, metadata: dict) -> bool:
        required_clearance = int(metadata.get("clearance", 1))
        if user.clearance < required_clearance:
            return False

        engagement = metadata.get("engagement")
        if engagement:
            if self.is_admin(user):
                return True
            return engagement in self.engagements_for(user)
        return True

    def filter(self, user: User, results: list[dict]) -> list[dict]:
        """results: list of dicts each having a 'metadata' key."""
        return [r for r in results if self.can_read(user, r.get("metadata", {}))]

    @staticmethod
    def is_admin(user: User) -> bool:
        return "admin" in user.roles

    @staticmethod
    def engagements_for(user: User) -> list[str]:
        """Engagement names this user holds an explicit role for. Shared by
        the in-process check above and PgVectorStore's SQL-level filter
        (pgvectorstore.py) so both derive 'what does this role mean' from the
        same place rather than maintaining two copies of the same logic."""
        return [r.split(":", 1)[1] for r in user.roles if r.startswith("engagement:")]
