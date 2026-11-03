"""
Team access: sign-in grants (INITIAL_ADMIN_EMAILS, invitations), the domain
rule, and the admin-only /admin team routes.

Runs against a separate, temporary Postgres database (created and dropped
here) so "last admin" and counts can't be affected by other data. Skipped
if Postgres isn't reachable.
"""

import logging
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.auth.access_settings import (
    ensure_access_settings_valid,
    parse_domain_list,
    parse_email_list,
)
from consultrag.config import settings

SECRET = "a-real-random-secret-for-team-tests-97531"


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


# --- settings parsing (no database) ------------------------------------------------------


def test_email_and_domain_lists_parse_and_normalise():
    assert parse_email_list(" Admin@Example.TEST , b@x.test ") == {"admin@example.test", "b@x.test"}
    assert parse_email_list("") == frozenset()
    assert parse_domain_list("Example.test, @other.test") == {"example.test", "other.test"}


@pytest.mark.parametrize("raw", ["not-an-email", "a@b", "a b@c.test", "a@c.test;b@d.test"])
def test_malformed_emails_fail_closed(raw):
    with pytest.raises(ValueError):
        parse_email_list(raw)
    with pytest.raises(RuntimeError, match="Refusing to start"):
        ensure_access_settings_valid(raw, "")


@pytest.mark.parametrize("raw", ["localhost", "exa mple.com", "*.example.com", "example..com"])
def test_malformed_domains_fail_closed(raw):
    with pytest.raises(RuntimeError, match="Refusing to start"):
        ensure_access_settings_valid("", raw)


def test_refusal_message_never_repeats_the_values():
    with pytest.raises(RuntimeError) as e:
        ensure_access_settings_valid("secret.person@nowhere", "")
    assert "secret.person" not in str(e.value)


# --- database-backed ---------------------------------------------------------------------

needs_pg = pytest.mark.skipif(not _pg_available(), reason="Postgres not reachable")


@pytest.fixture(scope="module")
def team_dsn():
    import psycopg

    name = f"consultrag_team_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(settings.database_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    base = settings.database_url.rsplit("/", 1)[0]
    yield f"{base}/{name}"
    with psycopg.connect(settings.database_url, autocommit=True) as admin:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,)
        )
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture
def repo(team_dsn):
    from consultrag.authz.repository import AuthzRepository

    r = AuthzRepository(dsn=team_dsn)
    with r.conn.cursor() as cur:
        cur.execute("TRUNCATE invitations, engagement_memberships, users, audit_events RESTART IDENTITY CASCADE")
    r.conn.commit()
    yield r
    r.close()


def _user(repo, email, sub=None):
    return repo.get_or_create_user(sub or f"sub-{uuid.uuid4().hex[:8]}", email)


def _make_admin(repo, uid, clearance=3):
    repo.add_membership(uid, None, "admin")
    repo.set_clearance(uid, clearance)


def _audit_rows(repo):
    with repo.conn.cursor() as cur:
        cur.execute("SELECT row_to_json(a)::text FROM audit_events a ORDER BY id")
        rows = [r[0] for r in cur.fetchall()]
    repo.conn.commit()
    return rows


def _invite(repo, email, engagements=("acme",), role="manager", clearance=2, is_admin=False, actor="1", ttl=14):
    from consultrag.authz.team import InviteSpec, create_invitation

    return create_invitation(repo.conn, actor, InviteSpec(email=email, engagements=list(engagements), role=role,
                                                          clearance=clearance, is_admin=is_admin), ttl)


# --- sign-in grants ---------------------------------------------------------------------------


@needs_pg
def test_initial_admin_granted_once_for_a_verified_email(repo, caplog):
    from consultrag.authz.team import apply_sign_in_grants

    uid = _user(repo, "boss@example.test")
    with caplog.at_level(logging.INFO, logger="consultrag.authz.team"):
        assert apply_sign_in_grants(repo.conn, uid, "Boss@Example.TEST", True, frozenset({"boss@example.test"})) == ["initial_admin"]
    user = repo.build_user(uid)
    assert "admin" in user.roles and user.clearance == 3
    assert any(f"user_id={uid}" in r.getMessage() for r in caplog.records)
    assert "boss@" not in caplog.text.lower()
    # Once: a later demotion sticks even though the email is still listed.
    with repo.conn.cursor() as cur:
        cur.execute("DELETE FROM engagement_memberships WHERE user_id = %s", (uid,))
    repo.conn.commit()
    assert apply_sign_in_grants(repo.conn, uid, "boss@example.test", True, frozenset({"boss@example.test"})) == []
    assert "admin" not in repo.build_user(uid).roles


@needs_pg
@pytest.mark.parametrize("verified", [False, None, "true", 1])
def test_unverified_email_never_gets_initial_admin_or_an_invitation(repo, verified):
    from consultrag.authz.team import apply_sign_in_grants

    uid = _user(repo, "boss@example.test")
    _invite(repo, "boss@example.test")
    assert apply_sign_in_grants(repo.conn, uid, "boss@example.test", verified, frozenset({"boss@example.test"})) == []
    user = repo.build_user(uid)
    assert user.roles == frozenset() and user.clearance == 1


@needs_pg
def test_invitation_applies_once_at_sign_in_with_case_differences(repo):
    from consultrag.authz.team import apply_sign_in_grants, list_invitations

    _invite(repo, "New.Person@Example.TEST", engagements=("acme", "globex"), role="manager", clearance=2)
    uid = _user(repo, "new.person@example.test")
    assert apply_sign_in_grants(repo.conn, uid, "NEW.person@example.test", True, frozenset()) == ["invitation"]
    user = repo.build_user(uid)
    assert {"engagement:acme", "engagement:globex"} <= user.roles and user.clearance == 2
    assert "admin" not in user.roles
    assert list_invitations(repo.conn) == []
    # Reuse: a second account with the same email gets nothing.
    other = _user(repo, "new.person@example.test")
    assert apply_sign_in_grants(repo.conn, other, "new.person@example.test", True, frozenset()) == []
    assert repo.build_user(other).roles == frozenset()


@needs_pg
def test_expired_and_revoked_invitations_grant_nothing(repo):
    from consultrag.authz.team import apply_sign_in_grants, revoke_invitation

    inv = _invite(repo, "late@example.test")
    with repo.conn.cursor() as cur:
        cur.execute("UPDATE invitations SET expires_at = now() - interval '1 minute' WHERE id = %s", (inv["id"],))
    repo.conn.commit()
    uid = _user(repo, "late@example.test")
    assert apply_sign_in_grants(repo.conn, uid, "late@example.test", True, frozenset()) == []

    inv2 = _invite(repo, "gone@example.test")  # a new one is allowed for another email
    revoke_invitation(repo.conn, "1", inv2["id"])
    uid2 = _user(repo, "gone@example.test")
    assert apply_sign_in_grants(repo.conn, uid2, "gone@example.test", True, frozenset()) == []
    assert repo.build_user(uid2).roles == frozenset()


# --- domain rule through the sign-in function --------------------------------------------------


class _Verifier:
    def __init__(self, email, verified=True):
        self.claims = {"sub": f"sub-{email}", "email": email, "email_verified": verified}

    def verify(self, token):
        return self.claims


@needs_pg
def test_domain_rule_allows_listed_domains_invited_emails_and_initial_admins(repo):
    from consultrag.auth.google_login import SignInRefused, authenticate_google_id_token

    def sign_in(email, **kw):
        return authenticate_google_id_token("Bearer x", _Verifier(email), repo,
                                            allowed_email_domains="example.test", **kw)

    assert sign_in("ok@Example.test").user_id
    with pytest.raises(SignInRefused):
        sign_in("outsider@other.test")
    with repo.conn.cursor() as cur:  # a refused account gets no user row
        cur.execute("SELECT count(*) FROM users WHERE lower(email) = 'outsider@other.test'")
        assert cur.fetchone()[0] == 0
    repo.conn.commit()
    _invite(repo, "guest@other.test")
    assert "engagement:acme" in sign_in("guest@other.test").roles
    boss = sign_in("boss@other.test", initial_admin_emails="boss@other.test")
    assert "admin" in boss.roles


@needs_pg
def test_malformed_domain_setting_refuses_sign_in(repo):
    from consultrag.auth.google_login import authenticate_google_id_token

    with pytest.raises(ValueError):
        authenticate_google_id_token("Bearer x", _Verifier("a@example.test"), repo,
                                     allowed_email_domains="not a domain")


# --- the admin routes -----------------------------------------------------------------------------


@pytest.fixture
def api(repo, team_dsn, monkeypatch):
    from fastapi.testclient import TestClient

    from consultrag.api.deps import get_authz_repo
    from consultrag.api.main import app
    from consultrag.authz.repository import AuthzRepository

    monkeypatch.setattr(settings, "app_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "dev_auth_bypass", False)

    def repo_dep():
        r = AuthzRepository(dsn=team_dsn)
        try:
            yield r
        finally:
            r.close()

    app.dependency_overrides[get_authz_repo] = repo_dep
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _bearer(repo, uid):
    from consultrag.auth.app_token import issue_app_token

    return {"Authorization": f"Bearer {issue_app_token(repo.build_user(uid), SECRET)}"}


ROUTES = [
    ("GET", "/admin/members", None),
    ("GET", "/admin/invitations", None),
    ("POST", "/admin/invitations", {"email": "x@example.test", "engagements": ["acme"]}),
    ("DELETE", "/admin/invitations/999", None),
    ("PATCH", "/admin/members/999", {"clearance": 2}),
    ("DELETE", "/admin/members/999", None),
    ("GET", "/admin/engagements", None),
]


@needs_pg
@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_team_route_requires_a_signed_in_admin(api, repo, method, path, body):
    nobody = _user(repo, "nobody@example.test")
    member = _user(repo, "member@example.test")
    repo.add_membership(member, "acme", "analyst")
    kw = {"json": body} if body is not None else {}
    assert api.request(method, path, **kw).status_code == 401
    assert api.request(method, path, headers=_bearer(repo, nobody), **kw).status_code == 403
    assert api.request(method, path, headers=_bearer(repo, member), **kw).status_code == 403


@needs_pg
def test_admin_token_is_rechecked_in_the_database(api, repo):
    admin = _user(repo, "a@example.test")
    _make_admin(repo, admin)
    headers = _bearer(repo, admin)  # token says admin
    with repo.conn.cursor() as cur:
        cur.execute("DELETE FROM engagement_memberships WHERE user_id = %s", (admin,))
    repo.conn.commit()
    assert api.get("/admin/members", headers=headers).status_code == 403


@needs_pg
def test_admin_can_invite_list_revoke_and_edit(api, repo):
    admin = _user(repo, "a@example.test")
    _make_admin(repo, admin)
    h = _bearer(repo, admin)
    r = api.post("/admin/invitations", headers=h,
                 json={"email": "Invitee@Example.test", "engagements": ["acme"], "role": "manager", "clearance": 2})
    assert r.status_code == 201 and r.json()["email"] == "invitee@example.test"
    inv_id = r.json()["id"]
    assert [i["id"] for i in api.get("/admin/invitations", headers=h).json()["invitations"]] == [inv_id]
    assert api.post("/admin/invitations", headers=h, json={"email": "invitee@example.test", "engagements": ["acme"]}).status_code == 409
    assert "acme" in api.get("/admin/engagements", headers=h).json()["engagements"]
    assert api.delete(f"/admin/invitations/{inv_id}", headers=h).status_code == 204
    assert api.delete(f"/admin/invitations/{inv_id}", headers=h).status_code == 404

    member = _user(repo, "m@example.test")
    r = api.patch(f"/admin/members/{member}", headers=h,
                  json={"clearance": 2, "engagements": [{"engagement": "acme", "role": "manager"}]})
    assert r.status_code == 200
    m = next(x for x in r.json()["members"] if x["user_id"] == str(member))
    assert m["clearance"] == 2 and m["engagements"] == [{"engagement": "acme", "role": "manager"}]
    assert m["preset"] == "manager"


@needs_pg
@pytest.mark.parametrize("body", [
    {"email": "bad", "engagements": ["acme"]},
    {"email": "x@example.test", "engagements": ["Bad Name!"]},
    {"email": "x@example.test", "engagements": ["acme"], "clearance": 0},
    {"email": "x@example.test", "engagements": ["acme"], "clearance": 6},
    {"email": "x@example.test", "engagements": []},
    {"email": "x@example.test", "engagements": ["acme"], "role": "owner"},
])
def test_invalid_invitations_are_rejected(api, repo, body):
    admin = _user(repo, "a@example.test")
    _make_admin(repo, admin)
    assert api.post("/admin/invitations", headers=_bearer(repo, admin), json=body).status_code == 422


@needs_pg
@pytest.mark.parametrize("clearance", [0, -1, 6, 99])
def test_invalid_clearance_is_rejected(api, repo, clearance):
    admin = _user(repo, "a@example.test")
    _make_admin(repo, admin)
    member = _user(repo, "m@example.test")
    assert api.patch(f"/admin/members/{member}", headers=_bearer(repo, admin), json={"clearance": clearance}).status_code == 422


@needs_pg
def test_engagement_label_admin_is_refused(api, repo):
    admin = _user(repo, "a@example.test")
    _make_admin(repo, admin)
    member = _user(repo, "m@example.test")
    r = api.patch(f"/admin/members/{member}", headers=_bearer(repo, admin),
                  json={"engagements": [{"engagement": "acme", "role": "admin"}]})
    assert r.status_code == 422
    assert "admin" not in repo.build_user(member).roles


@needs_pg
def test_last_admin_and_self_lockout_are_prevented(api, repo):
    admin = _user(repo, "a@example.test")
    _make_admin(repo, admin)
    h = _bearer(repo, admin)
    assert api.patch(f"/admin/members/{admin}", headers=h, json={"is_admin": False}).status_code == 409
    assert api.delete(f"/admin/members/{admin}", headers=h).status_code == 409
    assert "admin" in repo.build_user(admin).roles

    second = _user(repo, "b@example.test")
    _make_admin(repo, second)
    # Another admin may demote the first while two exist...
    assert api.patch(f"/admin/members/{admin}", headers=_bearer(repo, second), json={"is_admin": False}).status_code == 200
    # ...but not the last remaining one, even via a different route.
    third = _user(repo, "c@example.test")
    _make_admin(repo, third)
    assert api.delete(f"/admin/members/{third}", headers=_bearer(repo, second)).status_code == 200
    from consultrag.authz.team import remove_member, TeamError

    with pytest.raises(TeamError) as e:
        remove_member(repo.conn, "system", second)
    assert e.value.status == 409


@needs_pg
def test_removal_revokes_refresh_and_audit_rows_hold_no_emails(api, repo):
    from consultrag.auth.app_token import AppTokenError, issue_refresh_token, refresh_app_token

    admin = _user(repo, "a@example.test")
    _make_admin(repo, admin)
    member = _user(repo, "member.person@example.test")
    repo.add_membership(member, "acme", "analyst")
    refresh = issue_refresh_token(repo.build_user(member), SECRET, version=repo.refresh_version(member))
    assert refresh_app_token(refresh, SECRET, repo)  # works before removal

    h = _bearer(repo, admin)
    api.post("/admin/invitations", headers=h, json={"email": "invited.person@example.test", "engagements": ["globex"]})
    assert api.delete(f"/admin/members/{member}", headers=h).status_code == 200
    assert repo.build_user(member).roles == frozenset()
    with pytest.raises(AppTokenError):
        refresh_app_token(refresh, SECRET, repo)

    rows = _audit_rows(repo)
    actions = " ".join(rows)
    assert "access_removed" in actions and "invitation_created" in actions
    assert all("@" not in row for row in rows)
    assert f'"target_user_id":"{member}"' in actions.replace(" ", "")
