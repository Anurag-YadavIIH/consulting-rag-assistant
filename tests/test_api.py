"""
API tests. Authorization for /ingest, /query, /draft is decided entirely
from the access token's own claims (deps.py:get_current_app_user makes no DB
call) — so almost all of this suite needs no real Postgres and no network:
fake/in-memory dependencies are injected via FastAPI's dependency_overrides.
The one exception (test_admin_via_real_authz_store_crosses_engagements)
deliberately exercises the real Stage 1 Postgres schema, skipped cleanly if
unavailable, to prove the global-admin grant works end-to-end, not just as
an asserted test shortcut.
"""

import sys
import time
import uuid
from pathlib import Path

import pytest

jwt = pytest.importorskip("jwt", reason="pyjwt[crypto] not installed")
fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from consultrag.api.deps import get_authz_repo, get_current_app_user, get_ingestion_pipeline, get_rag_engine
from consultrag.api.main import app
from consultrag.auth.app_token import issue_app_token
from consultrag.config import settings
from consultrag.embeddings import HashEmbedder
from consultrag.pipeline import IngestionPipeline
from consultrag.rag import RAGEngine
from consultrag.security.access import User
from consultrag.vectorstore import NumpyVectorStore

SECRET = "a-real-random-secret-for-api-tests-987654321"
settings.app_jwt_secret = SECRET  # get_current_app_user reads this directly, not via Depends


# --- shared fixtures ---------------------------------------------------------


def _bearer(user: User) -> dict:
    token = issue_app_token(user, SECRET)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_store(tmp_path):
    """A NumpyVectorStore pre-loaded with two engagements' worth of clearly
    distinguishable content, so cross-engagement leakage is detectable by
    content, not just by id."""
    embedder = HashEmbedder(dim=256)
    store = NumpyVectorStore(dim=256)
    pipeline = IngestionPipeline(embedder=embedder, store=store)

    acme_file = tmp_path / "acme.txt"
    acme_file.write_text(
        "Acme is evaluating a neuronavigation platform. Reimbursement risk "
        "is the main ACME_BARRIER_TOKEN barrier to adoption."
    )
    globex_file = tmp_path / "globex.txt"
    globex_file.write_text(
        "Globex faces a GLOBEX_STRATEGIC_RISK_TOKEN competitive threat from "
        "incumbent device makers in remote neuromonitoring."
    )
    pipeline.ingest_path(acme_file, engagement="acme", clearance=1)
    pipeline.ingest_path(globex_file, engagement="globex", clearance=1)

    engine = RAGEngine(embedder=embedder, store=store)
    return embedder, store, engine, pipeline


@pytest.fixture
def client(sample_store):
    embedder, store, engine, pipeline = sample_store

    app.dependency_overrides[get_rag_engine] = lambda: engine
    app.dependency_overrides[get_ingestion_pipeline] = lambda: pipeline
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _acme_user(clearance: int = 2) -> User:
    return User.make("1", roles=["analyst", "engagement:acme"], clearance=clearance)


def _admin_user() -> User:
    return User.make("99", roles=["admin"], clearance=5)


# --- authentication gate: 401s ------------------------------------------------


def test_query_with_no_token_is_401(client):
    resp = client.post("/query", json={"question": "anything"})
    assert resp.status_code == 401


def test_query_with_malformed_token_is_401(client):
    resp = client.post(
        "/query", json={"question": "anything"}, headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401


def test_query_with_expired_app_token_is_401(client):
    expired = issue_app_token(_acme_user(), SECRET, expires_in=-1)
    resp = client.post(
        "/query", json={"question": "anything"}, headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401


def test_query_with_google_style_token_is_401(client):
    # RS256, not HS256 — verify_app_token must reject it regardless of any
    # claims it carries (see test_app_token.py for the cross-verifier proof
    # at the unit level; this confirms it holds through the actual route).
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    now = int(time.time())
    google_token = jwt.encode(
        {"sub": "google-sub", "email": "x@example.com", "iat": now, "exp": now + 300},
        priv_pem, algorithm="RS256", headers={"kid": "key-a"},
    )
    resp = client.post(
        "/query", json={"question": "anything"}, headers={"Authorization": f"Bearer {google_token}"}
    )
    assert resp.status_code == 401


def test_ingest_with_no_token_is_401(client):
    resp = client.post("/ingest", json={"path": "data/sample/acme_research.txt", "engagement": "acme"})
    assert resp.status_code == 401


def test_draft_with_no_token_is_401(client):
    resp = client.post("/draft", json={"topic": "anything"})
    assert resp.status_code == 401


def test_me_with_no_token_is_401(client):
    resp = client.get("/me")
    assert resp.status_code == 401


def test_me_reflects_token_derived_identity(client):
    user = _acme_user(clearance=2)
    resp = client.get("/me", headers=_bearer(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "1"
    assert body["engagements"] == ["acme"]
    assert body["is_admin"] is False
    assert body["clearance"] == 2


def test_me_for_admin_has_no_specific_engagements(client):
    admin = _admin_user()
    resp = client.get("/me", headers=_bearer(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_admin"] is True
    assert body["engagements"] == []


# --- authorization / isolation: the core of this stage -----------------------


def test_query_forbidden_engagement_returns_403_and_leaks_nothing(client):
    user = _acme_user()  # only a member of "acme"
    resp = client.post(
        "/query", json={"question": "what is the strategic risk?", "engagement": "globex"},
        headers=_bearer(user),
    )
    assert resp.status_code == 403
    body = resp.json()
    assert set(body.keys()) == {"detail"}  # nothing else — no answer, no citations, no counts
    assert "GLOBEX" not in str(body)


def test_ingest_into_forbidden_engagement_returns_403(client):
    user = _acme_user()
    resp = client.post(
        "/ingest",
        json={"path": "data/sample/acme_research.txt", "engagement": "globex", "clearance": 1},
        headers=_bearer(user),
    )
    assert resp.status_code == 403


def test_ingest_above_own_clearance_returns_403(client):
    user = _acme_user(clearance=1)
    resp = client.post(
        "/ingest",
        json={"path": "data/sample/acme_research.txt", "engagement": "acme", "clearance": 5},
        headers=_bearer(user),
    )
    assert resp.status_code == 403


def test_query_without_explicit_scope_never_leaks_other_engagement(client):
    user = _acme_user()  # member of "acme" only, NOT "globex"
    resp = client.post(
        "/query", json={"question": "what is the competitive threat and strategic risk?"},
        headers=_bearer(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    # Assert at the response level: globex's distinguishing token must never
    # appear in the answer text, and no citation may point at a globex
    # source — check both, since ExtractiveLLM only echoes the single
    # top-ranked chunk into `answer`, while citations list every chunk
    # actually retrieved.
    assert "GLOBEX_STRATEGIC_RISK_TOKEN" not in body["answer"]
    for citation in body["citations"]:
        assert "globex" not in citation["source_path"].lower()


def test_query_allowed_engagement_returns_200_with_content(client):
    user = _acme_user()
    resp = client.post(
        "/query", json={"question": "what is the barrier to adoption?", "engagement": "acme"},
        headers=_bearer(user),
    )
    assert resp.status_code == 200
    assert "ACME_BARRIER_TOKEN" in resp.json()["answer"]


def test_spoofed_engagement_in_body_is_rejected_not_substituted(client):
    # Caller's token says "acme" only. Body claims "globex". The system must
    # NOT silently fall back to the token's real engagement and return 200 —
    # it must reject the mismatch outright.
    user = _acme_user()
    resp = client.post(
        "/query", json={"question": "anything", "engagement": "globex"}, headers=_bearer(user)
    )
    assert resp.status_code == 403


def test_spoofed_clearance_in_ingest_body_is_rejected(client):
    user = _acme_user(clearance=1)
    resp = client.post(
        "/ingest",
        json={"path": "data/sample/acme_research.txt", "engagement": "acme", "clearance": 99},
        headers=_bearer(user),
    )
    assert resp.status_code == 403


def test_spoofed_engagement_and_clearance_together_are_both_rejected(client):
    # Single request spoofing BOTH fields at once: the token says clearance=1
    # and membership in "acme" only; the body claims "globex" (not held) AND
    # clearance=99 (above the token's own). The server rejects outright — it
    # does not fall back to the token's real engagement/clearance and
    # partially proceed; nothing is ingested and nothing beyond the error
    # detail comes back.
    user = _acme_user(clearance=1)
    resp = client.post(
        "/ingest",
        json={"path": "data/sample/acme_research.txt", "engagement": "globex", "clearance": 99},
        headers=_bearer(user),
    )
    assert resp.status_code == 403
    body = resp.json()
    assert set(body.keys()) == {"detail"}  # no chunks_ingested, no partial-success info


def test_admin_role_from_token_crosses_engagements(client):
    # Admin-via-token (not yet the real authz-store path — see the dedicated
    # Postgres-backed test below for that). ExtractiveLLM only echoes the
    # single top-ranked chunk into `answer`, so assert on citations (which
    # include every retrieved chunk) to confirm globex was actually reachable.
    admin = _admin_user()
    resp = client.post(
        "/query", json={"question": "what is the competitive threat?", "engagement": "globex"},
        headers=_bearer(admin),
    )
    assert resp.status_code == 200
    sources = [c["source_path"] for c in resp.json()["citations"]]
    assert any("globex" in s.lower() for s in sources)


# --- defense-in-depth: AccessPolicy backstop, even with zero SQL filtering --


def test_isolation_holds_via_accesspolicy_alone_no_sql_filtering_involved(client):
    # NumpyVectorStore (used by the `client`/`sample_store` fixtures here)
    # has NO SQL-level filtering at all — proves AccessPolicy.filter() in
    # rag.py is independently sufficient, not merely decorative alongside
    # PgVectorStore's defense-in-depth filter.
    user = _acme_user()
    resp = client.post(
        "/query", json={"question": "what is the competitive threat and strategic risk?"},
        headers=_bearer(user),
    )
    assert resp.status_code == 200
    assert "GLOBEX_STRATEGIC_RISK_TOKEN" not in resp.json()["answer"]


# --- draft mirrors query's isolation rules -----------------------------------


def test_draft_forbidden_engagement_returns_403(client):
    user = _acme_user()
    resp = client.post(
        "/draft", json={"topic": "strategic risk", "engagement": "globex"}, headers=_bearer(user)
    )
    assert resp.status_code == 403


# --- /auth/login and /auth/refresh: fakes, no real Postgres needed ----------


class _FakeAuthzRepository:
    def __init__(self):
        self._next_id = 1
        self._by_sub: dict[str, int] = {}
        self._authz: dict[int, dict] = {}

    def get_or_create_user(self, google_sub: str, email: str) -> int:
        if google_sub not in self._by_sub:
            user_id = self._next_id
            self._next_id += 1
            self._by_sub[google_sub] = user_id
            self._authz[user_id] = {"roles": frozenset({"analyst"}), "clearance": 1}
        return self._by_sub[google_sub]

    def build_user(self, user_id: int) -> User:
        info = self._authz[user_id]
        return User(user_id=str(user_id), roles=info["roles"], clearance=info["clearance"])


def test_login_with_invalid_google_token_is_401(client, monkeypatch):
    app.dependency_overrides[get_authz_repo] = lambda: _FakeAuthzRepository()
    resp = client.post("/auth/login", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_refresh_with_invalid_token_is_401(client):
    app.dependency_overrides[get_authz_repo] = lambda: _FakeAuthzRepository()
    resp = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401


# --- one real-Postgres test: admin via the actual authz store ---------------


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


@pytest.mark.skipif(not _pg_available(), reason="Postgres not reachable")
def test_admin_via_real_authz_store_crosses_engagements(client):
    # Exercises Stage 1's real schema end-to-end: a row with
    # (engagement=NULL, role='admin') in the actual Postgres
    # engagement_memberships table, loaded through build_user() — not a
    # User.make() shortcut — then used to authenticate an API request.
    from consultrag.authz.repository import AuthzRepository

    repo = AuthzRepository()
    google_sub = f"test-consultrag-{uuid.uuid4().hex[:12]}"
    try:
        user_id = repo.get_or_create_user(google_sub, "admin@example.com")
        repo.add_membership(user_id, None, "admin")
        admin_user = repo.build_user(user_id)

        resp = client.post(
            "/query", json={"question": "what is the competitive threat?", "engagement": "globex"},
            headers=_bearer(admin_user),
        )
        assert resp.status_code == 200
        sources = [c["source_path"] for c in resp.json()["citations"]]
        assert any("globex" in s.lower() for s in sources)
    finally:
        with repo._conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE google_sub = %(sub)s", {"sub": google_sub})
        repo._conn.commit()
        repo.close()


# --- DEV_AUTH_BYPASS: fail loud, fail closed --------------------------------


def test_dev_bypass_off_has_no_effect(client):
    # Default (dev_auth_bypass=False) — normal auth still required, same as
    # every other 401 test in this file.
    resp = client.post("/query", json={"question": "anything"})
    assert resp.status_code == 401


def test_dev_bypass_on_with_explicit_dev_env_injects_dev_user(sample_store, monkeypatch):
    embedder, store, engine, pipeline = sample_store
    monkeypatch.setattr(settings, "dev_auth_bypass", True)
    monkeypatch.setattr(settings, "app_env", "development")
    app.dependency_overrides[get_rag_engine] = lambda: engine
    app.dependency_overrides[get_ingestion_pipeline] = lambda: pipeline
    try:
        with TestClient(app) as c:
            # No Authorization header at all — bypass must still let this
            # through, proving the dev User was actually injected.
            resp = c.post(
                "/query", json={"question": "what is the barrier to adoption?", "engagement": "acme"}
            )
            assert resp.status_code == 200
            assert "ACME_BARRIER_TOKEN" in resp.json()["answer"]
    finally:
        app.dependency_overrides.clear()


def test_dev_bypass_on_with_production_app_env_refuses_to_start(monkeypatch):
    monkeypatch.setattr(settings, "dev_auth_bypass", True)
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass


def test_dev_bypass_on_with_unset_app_env_refuses_to_start(monkeypatch):
    # The fail-closed-BY-DEFAULT case: APP_ENV missing entirely (None) must
    # NOT be treated as "fine, not literally production" — it must deny
    # bypass exactly like an explicit non-dev value would. This is the
    # property that distinguishes a whitelist from a blacklist.
    monkeypatch.setattr(settings, "dev_auth_bypass", True)
    monkeypatch.setattr(settings, "app_env", None)
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass
