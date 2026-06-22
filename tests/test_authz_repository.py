"""
AuthzRepository tests against a real Postgres instance. Skip cleanly (not
fail) if psycopg isn't installed or Postgres isn't reachable, so
`pytest tests/ -q` stays green offline — run `docker compose up -d` first to
actually exercise this file.

Rows use google_sub values prefixed 'test-consultrag-' so they're
identifiable and can be cleaned up without touching real seeded users;
teardown deletes by that prefix (engagement_memberships cascade via
ON DELETE CASCADE).
"""

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.config import settings
from consultrag.security.access import AccessPolicy


def _pg_available() -> bool:
    try:
        import psycopg
    except ImportError:
        return False
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="Postgres not reachable")


@pytest.fixture
def repo():
    from consultrag.authz.repository import AuthzRepository

    r = AuthzRepository()
    yield r
    with r._conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE google_sub LIKE 'test-consultrag-%'")
    r._conn.commit()
    r.close()


def _sub() -> str:
    return f"test-consultrag-{uuid.uuid4().hex[:12]}"


def test_get_or_create_user_is_idempotent(repo):
    sub = _sub()
    id1 = repo.get_or_create_user(sub, "a@example.com")
    id2 = repo.get_or_create_user(sub, "a@example.com")
    assert id1 == id2


def test_get_or_create_user_updates_email_on_conflict(repo):
    sub = _sub()
    user_id = repo.get_or_create_user(sub, "old@example.com")
    repo.get_or_create_user(sub, "new@example.com")
    with repo._conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE id = %(id)s", {"id": user_id})
        assert cur.fetchone()[0] == "new@example.com"


def test_get_user_authz_default_clearance_and_no_memberships(repo):
    user_id = repo.get_or_create_user(_sub(), "b@example.com")
    info = repo.get_user_authz(user_id)
    assert info.clearance == 1
    assert info.engagements == []
    assert info.roles == frozenset()


def test_get_user_authz_reflects_engagement_membership(repo):
    user_id = repo.get_or_create_user(_sub(), "c@example.com")
    repo.set_clearance(user_id, 2)
    repo.add_membership(user_id, "acme", "analyst")
    info = repo.get_user_authz(user_id)
    assert info.clearance == 2
    assert info.engagements == ["acme"]
    assert "engagement:acme" in info.roles
    assert "analyst" in info.roles


def test_get_user_authz_reflects_global_admin_role(repo):
    user_id = repo.get_or_create_user(_sub(), "d@example.com")
    repo.add_membership(user_id, None, "admin")
    info = repo.get_user_authz(user_id)
    assert "admin" in info.roles
    assert info.engagements == []  # a global grant carries no engagement


def test_add_membership_is_idempotent_including_global_admin(repo):
    # Proves UNIQUE NULLS NOT DISTINCT actually holds: without it, two
    # (user_id, NULL, 'admin') rows would NOT collide under default Postgres
    # NULL semantics, and ON CONFLICT DO NOTHING would silently insert a
    # duplicate instead of deduplicating.
    user_id = repo.get_or_create_user(_sub(), "f@example.com")
    repo.add_membership(user_id, None, "admin")
    repo.add_membership(user_id, None, "admin")
    with repo._conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM engagement_memberships WHERE user_id = %(id)s",
            {"id": user_id},
        )
        assert cur.fetchone()[0] == 1
    info = repo.get_user_authz(user_id)
    assert info.roles == frozenset({"admin"})


def test_build_user_works_with_real_access_policy(repo):
    user_id = repo.get_or_create_user(_sub(), "e@example.com")
    repo.set_clearance(user_id, 2)
    repo.add_membership(user_id, "acme", "analyst")
    user = repo.build_user(user_id)

    policy = AccessPolicy()
    assert policy.can_read(user, {"engagement": "acme", "clearance": 2})
    assert not policy.can_read(user, {"engagement": "globex", "clearance": 1})
    assert not policy.can_read(user, {"engagement": "acme", "clearance": 3})
