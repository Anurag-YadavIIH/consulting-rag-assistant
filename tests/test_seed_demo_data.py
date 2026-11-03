"""scripts/seed_demo_data.py: the local-only guards and the minimal grant,
with fake pipeline and repository (no database, no model)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import seed_demo_data as seed  # noqa: E402

LOCAL = "postgresql://consultrag:consultrag@postgres:5432/consultrag"


class FakePipeline:
    def __init__(self):
        self.calls = []

    def ingest_path(self, path, **kw):
        self.calls.append((Path(path).name, kw))
        return 1


class FakeRepo:
    def __init__(self, existing=(90,)):
        self.existing = set(existing)
        self.memberships = []
        self.closed = False

    def user_exists(self, uid):
        return uid in self.existing

    def add_membership(self, uid, engagement, role):
        self.memberships.append((uid, engagement, role))

    def close(self):
        self.closed = True


def run(argv, *, app_env="development", url=LOCAL, pipeline=None, repo=None):
    pipeline = pipeline or FakePipeline()
    repo = repo or FakeRepo()
    code = seed.main(argv, app_env=app_env, database_url=url,
                     pipeline_factory=lambda: pipeline, repo_factory=lambda: repo)
    return code, pipeline, repo


@pytest.mark.parametrize("env", ["production", "Production", " production "])
def test_refuses_production(env, capsys):
    code, pipeline, _ = run([], app_env=env)
    assert code == 2 and pipeline.calls == []
    assert "production" in capsys.readouterr().err


@pytest.mark.parametrize("url", [
    "postgresql://u:p@consultrag.abc123.ap-south-1.rds.amazonaws.com:5432/db",
    "postgresql://u:p@10.0.0.5:5432/db",
    "postgresql://u:p@db.example.com/db",
])
def test_refuses_non_local_databases(url):
    code, pipeline, _ = run([], url=url)
    assert code == 2 and pipeline.calls == []


@pytest.mark.parametrize("url", [LOCAL, "postgresql://u:p@localhost:5432/db", "postgresql://u:p@127.0.0.1/db"])
def test_runs_locally_and_loads_both_demo_engagements(url):
    code, pipeline, repo = run([], url=url)
    assert code == 0
    engagements = {kw["engagement"] for _, kw in pipeline.calls}
    assert engagements == {"meridian", "kestrel"}
    assert all(kw["clearance"] == 1 and kw["source_name"] == name for name, kw in pipeline.calls)
    assert repo.memberships == []  # no grant unless asked


def test_grant_is_analyst_in_the_two_demo_engagements_only():
    code, _, repo = run(["--grant-user-id", "90"])
    assert code == 0
    assert sorted(repo.memberships) == [(90, "kestrel", "analyst"), (90, "meridian", "analyst")]
    assert repo.closed


def test_grant_for_an_unknown_user_fails_before_loading_anything(capsys):
    code, pipeline, repo = run(["--grant-user-id", "5"], repo=FakeRepo(existing=()))
    assert code == 1 and pipeline.calls == [] and repo.memberships == []
    assert "no user with id 5" in capsys.readouterr().err


def test_demo_files_are_the_fictional_notes():
    files = seed.demo_files()
    assert len(files) == 4
    for _, path in files:
        assert path.is_relative_to(ROOT / "data" / "demo")
