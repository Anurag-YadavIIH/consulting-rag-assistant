"""scripts/seed_authz.py against an in-memory repository (no Postgres)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("psycopg", reason="seed_authz imports the real repository module")

import seed_authz  # noqa: E402


class _FakeRepo:
    def __init__(self, existing=(7,)):
        self.users = set(existing)
        self.calls = []

    def user_exists(self, user_id):
        return user_id in self.users

    def get_or_create_user(self, google_sub, email):
        self.calls.append(("get_or_create_user",))
        self.users.add(99)
        return 99

    def set_clearance(self, user_id, clearance):
        self.calls.append(("set_clearance", user_id, clearance))

    def add_membership(self, user_id, engagement, role):
        self.calls.append(("add_membership", user_id, engagement, role))

    def close(self):
        self.calls.append(("close",))


def _run(argv, repo):
    return seed_authz.main(argv, repo_factory=lambda: repo)


def test_user_id_grants_only_what_is_asked(capsys):
    repo = _FakeRepo()
    assert _run(["--user-id", "7", "--engagement", "acme"], repo) == 0
    assert repo.calls == [("add_membership", 7, "acme", "analyst"), ("close",)]
    assert "user_id=7: analyst in acme." in capsys.readouterr().out


def test_user_id_with_nothing_to_grant_fails_before_touching_the_db():
    repo = _FakeRepo()
    with pytest.raises(SystemExit) as e:
        _run(["--user-id", "7"], repo)
    assert e.value.code == 2
    assert repo.calls == []


def test_unknown_user_id_fails_clearly_and_grants_nothing(capsys):
    repo = _FakeRepo(existing=())
    assert _run(["--user-id", "5", "--admin"], repo) == 1
    assert "no user with id 5" in capsys.readouterr().err
    assert repo.calls == [("close",)]


def test_user_id_admin_and_clearance(capsys):
    repo = _FakeRepo()
    assert _run(["--user-id", "7", "--admin", "--clearance", "2"], repo) == 0
    assert ("add_membership", 7, None, "admin") in repo.calls
    assert ("set_clearance", 7, 2) in repo.calls


@pytest.mark.parametrize("clearance", ["0", "4", "5"])
def test_clearance_outside_one_to_three_is_refused(clearance):
    repo = _FakeRepo()
    with pytest.raises(SystemExit):
        _run(["--user-id", "7", "--clearance", clearance], repo)
    assert repo.calls == []


def test_engagement_role_admin_is_refused():
    repo = _FakeRepo()
    with pytest.raises(SystemExit):
        _run(["--user-id", "7", "--engagement", "acme", "--role", "admin"], repo)
    assert repo.calls == []


def test_google_sub_mode_never_prints_the_email_or_subject(capsys):
    repo = _FakeRepo()
    assert _run(["--google-sub", "sub-SECRETLY-123", "--email", "me@example.com",
                 "--engagement", "acme"], repo) == 0
    out = capsys.readouterr().out
    assert "sub-SECRETLY-123" not in out and "me@example.com" not in out
    assert ("set_clearance", 99, 1) in repo.calls


def test_user_id_and_google_sub_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        _run(["--user-id", "7", "--google-sub", "x", "--email", "y", "--admin"], _FakeRepo())
