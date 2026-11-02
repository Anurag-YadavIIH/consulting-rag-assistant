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
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

jwt = pytest.importorskip("jwt", reason="pyjwt[crypto] not installed")
fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from consultrag.api.deps import get_authz_repo, get_current_app_user, get_ingestion_pipeline, get_rag_engine
from consultrag.api.main import app
from consultrag.api.routes.ingest import clean_filename
from consultrag.auth.app_token import issue_app_token
from consultrag.config import settings
from consultrag.embeddings import HashEmbedder
from consultrag.pipeline import IngestionPipeline
from consultrag.rag import RAGEngine
from consultrag.security.access import User
from consultrag.security.redaction import Redactor
from consultrag.vectorstore import NumpyVectorStore, StoredChunk

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


@pytest.fixture
def dev_env(monkeypatch):
    """Path-based POST /ingest is development-only (404 otherwise). Tests of
    its auth rules opt into a dev APP_ENV so they still exercise those rules."""
    monkeypatch.setattr(settings, "app_env", "development")


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


def test_ingest_with_no_token_is_401(client, dev_env):
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


def test_ingest_into_forbidden_engagement_returns_403(client, dev_env):
    user = _acme_user()
    resp = client.post(
        "/ingest",
        json={"path": "data/sample/acme_research.txt", "engagement": "globex", "clearance": 1},
        headers=_bearer(user),
    )
    assert resp.status_code == 403


def test_ingest_above_own_clearance_returns_403(client, dev_env):
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


def test_spoofed_clearance_in_ingest_body_is_rejected(client, dev_env):
    user = _acme_user(clearance=1)
    resp = client.post(
        "/ingest",
        json={"path": "data/sample/acme_research.txt", "engagement": "acme", "clearance": 99},
        headers=_bearer(user),
    )
    assert resp.status_code == 403


def test_spoofed_engagement_and_clearance_together_are_both_rejected(client, dev_env):
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


def test_health_needs_no_auth():
    with TestClient(app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "0.2.0"}


# --- path-based /ingest: development only ------------------------------------


@pytest.mark.parametrize("app_env", ["production", None, "", "devel", "staging"])
def test_path_ingest_is_404_outside_development(client, monkeypatch, app_env):
    monkeypatch.setattr(settings, "app_env", app_env)
    resp = client.post(
        "/ingest",
        json={"path": "data/sample/acme_research.txt", "engagement": "acme", "clearance": 1},
        headers=_bearer(_acme_user()),
    )
    assert resp.status_code == 404


def test_path_ingest_is_404_in_production_even_without_token(client, monkeypatch):
    # The route must look absent, not "present but needs auth".
    monkeypatch.setattr(settings, "app_env", "production")
    resp = client.post("/ingest", json={"path": "x.txt", "engagement": "acme"})
    assert resp.status_code == 404


def test_path_ingest_works_in_development(client, sample_store, dev_env, tmp_path):
    _, store, _, _ = sample_store
    f = tmp_path / "dev_note.txt"
    f.write_text("A development-only DEV_PATH_TOKEN note.")
    resp = client.post(
        "/ingest",
        json={"path": str(f), "engagement": "acme", "clearance": 1},
        headers=_bearer(_acme_user()),
    )
    assert resp.status_code == 200
    assert resp.json()["chunks_ingested"] >= 1
    assert any("DEV_PATH_TOKEN" in c.text for c in store.all_chunks())


# --- POST /ingest/upload ------------------------------------------------------


def _upload(client, user, filename, content, engagement="acme", clearance=1):
    headers = _bearer(user) if user is not None else {}
    return client.post(
        "/ingest/upload",
        files={"file": (filename, content, "application/octet-stream")},
        data={"engagement": engagement, "clearance": str(clearance)},
        headers=headers,
    )


def _doc_chunks(store, engagement, name):
    return [
        c for c in store.all_chunks()
        if c.metadata.get("engagement") == engagement and c.metadata.get("source_path") == name
    ]


@pytest.fixture
def upload_tmp(tmp_path, monkeypatch):
    """Points tempfile at a fresh, nested directory so tests can prove the
    route writes only there and leaves nothing behind."""
    root = tmp_path / "a" / "b"
    root.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def test_upload_success_ingests_and_cites_original_filename(client, sample_store):
    _, store, _, _ = sample_store
    resp = _upload(client, _acme_user(), "acme_notes.txt",
                   b"The UPLOAD_MARKER_TOKEN shows uploads reach retrieval.")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_name"] == "acme_notes.txt"
    assert body["chunks_ingested"] >= 1
    stored = _doc_chunks(store, "acme", "acme_notes.txt")
    assert stored and all(c.chunk_id.startswith("upload://acme/acme_notes.txt#") for c in stored)

    resp = client.post(
        "/query", json={"question": "UPLOAD_MARKER_TOKEN uploads", "engagement": "acme"},
        headers=_bearer(_acme_user()),
    )
    assert resp.status_code == 200
    sources = [c["source_path"] for c in resp.json()["citations"]]
    assert "acme_notes.txt" in sources
    # No citation leaks the temporary file's path or fixed name.
    assert not any("consultrag-upload-" in s or s.endswith("/upload.txt") for s in sources)


def test_upload_redacts_pii_and_custom_terms_before_storage(sample_store):
    embedder, store, engine, _ = sample_store
    embedded_texts: list[str] = []

    class RecordingEmbedder:
        dim = embedder.dim

        def embed(self, texts):
            embedded_texts.extend(texts)
            return embedder.embed(texts)

    pipeline = IngestionPipeline(
        embedder=RecordingEmbedder(), store=store,
        redactor=Redactor(extra_terms=["Project Helios"]),
    )
    app.dependency_overrides[get_rag_engine] = lambda: engine
    app.dependency_overrides[get_ingestion_pipeline] = lambda: pipeline
    try:
        with TestClient(app) as c:
            resp = _upload(c, _acme_user(), "helios.txt",
                           b"Project Helios lead is jane.doe@example.com, phone 415-555-0134.")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200

    stored_text = " ".join(c.text for c in _doc_chunks(store, "acme", "helios.txt"))
    for raw in ("Project Helios", "jane.doe@example.com", "415-555-0134"):
        assert raw not in stored_text          # what is actually persisted
        assert all(raw not in t for t in embedded_texts)  # and what was embedded
    assert "[REDACTED_EMAIL]" in stored_text


def test_upload_with_no_token_is_401(client, sample_store):
    _, store, _, _ = sample_store
    resp = _upload(client, None, "a.txt", b"anything")
    assert resp.status_code == 401
    assert _doc_chunks(store, "acme", "a.txt") == []


def test_upload_into_wrong_engagement_is_403(client, sample_store):
    _, store, _, _ = sample_store
    resp = _upload(client, _acme_user(), "a.txt", b"anything", engagement="globex")
    assert resp.status_code == 403
    assert _doc_chunks(store, "globex", "a.txt") == []


def test_upload_above_own_clearance_is_403(client, sample_store):
    _, store, _, _ = sample_store
    resp = _upload(client, _acme_user(clearance=1), "a.txt", b"anything", clearance=5)
    assert resp.status_code == 403
    assert _doc_chunks(store, "acme", "a.txt") == []


@pytest.mark.parametrize("filename", ["tool.exe", "notes.docx", "meeting.mp3", "noextension"])
def test_upload_unsupported_type_is_415(client, filename):
    resp = _upload(client, _acme_user(), filename, b"some bytes")
    assert resp.status_code == 415
    assert ".pdf" in resp.json()["detail"]  # lists what IS supported


def test_upload_oversized_file_is_413(client, sample_store, monkeypatch, upload_tmp):
    _, store, _, _ = sample_store
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    resp = _upload(client, _acme_user(), "big.txt", b"a" * (1024 * 1024 + 1))
    assert resp.status_code == 413
    assert _doc_chunks(store, "acme", "big.txt") == []
    assert list(upload_tmp.iterdir()) == []


def test_upload_exactly_at_limit_is_accepted(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    resp = _upload(client, _acme_user(), "edge.txt", b"word. " * (1024 * 1024 // 6))
    assert resp.status_code == 200


def test_upload_empty_file_is_400(client):
    resp = _upload(client, _acme_user(), "empty.txt", b"")
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"]


@pytest.mark.parametrize("filename", ["broken.pdf", "broken.pptx"])
def test_upload_unreadable_file_is_422(client, sample_store, filename):
    _, store, _, _ = sample_store
    resp = _upload(client, _acme_user(), filename, b"this is not really a pdf or a pptx")
    assert resp.status_code == 422
    assert _doc_chunks(store, "acme", filename) == []


def test_upload_with_no_extractable_text_is_422(client):
    resp = _upload(client, _acme_user(), "blank.txt", b"   \n\n  ")
    assert resp.status_code == 422


@pytest.mark.parametrize("filename", [
    "../../secret.txt", "..\\..\\secret.txt", "/etc/secret.txt", "C:\\Windows\\secret.txt",
])
def test_upload_malicious_filename_is_reduced_to_a_label(client, sample_store, upload_tmp, filename):
    _, store, _, _ = sample_store
    resp = _upload(client, _acme_user(), filename, b"Path traversal attempt content.")
    assert resp.status_code == 200
    assert resp.json()["source_name"] == "secret.txt"
    assert _doc_chunks(store, "acme", "secret.txt")
    # Nothing named secret.txt was written anywhere, inside or above the temp root.
    assert list(upload_tmp.parents[1].rglob("secret.txt")) == []
    assert list(upload_tmp.iterdir()) == []


def _raw_upload(client, user, raw_filename: str, content: bytes, engagement="acme"):
    # httpx percent-encodes control characters in multipart filenames, but a
    # hostile client can send them raw, so build the body by hand.
    b = b"XBOUNDARYX"
    body = (
        b"--" + b + b'\r\nContent-Disposition: form-data; name="engagement"\r\n\r\n'
        + engagement.encode() + b"\r\n"
        + b"--" + b + b'\r\nContent-Disposition: form-data; name="file"; filename="'
        + raw_filename.encode("utf-8") + b'"\r\nContent-Type: text/plain\r\n\r\n'
        + content + b"\r\n--" + b + b"--\r\n"
    )
    return client.post(
        "/ingest/upload", content=body,
        headers={**_bearer(user), "Content-Type": f"multipart/form-data; boundary={b.decode()}"},
    )


def test_upload_filename_control_characters_are_removed(client, sample_store):
    _, store, _, _ = sample_store
    resp = _raw_upload(client, _acme_user(), "re\u202eport\t\x07\x1b.txt", b"Some content.")
    assert resp.status_code == 200
    assert resp.json()["source_name"] == "report.txt"
    assert _doc_chunks(store, "acme", "report.txt")


@pytest.mark.parametrize("raw, expected", [
    ("../../secret.txt", "secret.txt"),
    ("a\\b/c\\d.pdf", "d.pdf"),
    ("re\u202eport\t\x07.txt", "report.txt"),
    ("  spaced name.md  ", "spaced name.md"),
])
def test_clean_filename_unit(raw, expected):
    assert clean_filename(raw) == expected


@pytest.mark.parametrize("filename", ["x" * 252 + ".txt", "..", "/", "\x07\x08"])
def test_upload_unusable_or_overlong_filename_is_400(client, filename):
    resp = _raw_upload(client, _acme_user(), filename, b"Some content.")
    assert resp.status_code == 400


def test_upload_temp_file_is_created_in_temp_dir_and_always_removed(
    client, sample_store, upload_tmp, monkeypatch
):
    _, _, _, pipeline = sample_store
    seen: list[Path] = []
    real_ingest = pipeline.ingest_path

    def spy(path, **kwargs):
        seen.append(Path(path))
        assert Path(path).exists()
        return real_ingest(path, **kwargs)

    monkeypatch.setattr(pipeline, "ingest_path", spy)

    ok = _upload(client, _acme_user(), "fine.txt", b"Perfectly fine content.")
    assert ok.status_code == 200
    bad = _upload(client, _acme_user(), "broken.pdf", b"not a pdf")
    assert bad.status_code == 422

    assert len(seen) == 2
    for p in seen:
        assert upload_tmp in p.parents           # written under the temp root only
        assert p.name in ("upload.txt", "upload.pdf")  # fixed name, not the upload's
        assert not p.exists()
    assert list(upload_tmp.iterdir()) == []


def test_upload_temp_dir_removed_when_pipeline_crashes(sample_store, upload_tmp, monkeypatch):
    embedder, store, engine, pipeline = sample_store

    def boom(texts):
        raise RuntimeError("embedder down")

    monkeypatch.setattr(pipeline.embedder, "embed", boom)
    app.dependency_overrides[get_rag_engine] = lambda: engine
    app.dependency_overrides[get_ingestion_pipeline] = lambda: pipeline
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = _upload(c, _acme_user(), "crash.txt", b"Some content.")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 500
    assert list(upload_tmp.iterdir()) == []


# --- re-uploading an existing filename: 409 / atomic replacement ------------


def test_replace_blocked_with_409_when_existing_chunk_is_above_uploader(client, sample_store):
    _, store, _, _ = sample_store
    high = _upload(client, _acme_user(clearance=3), "plan.txt",
                   b"The SECRET_PLAN_TOKEN is classified.", clearance=3)
    assert high.status_code == 200
    before = [(c.chunk_id, c.text, c.metadata["clearance"]) for c in _doc_chunks(store, "acme", "plan.txt")]

    resp = _upload(client, _acme_user(clearance=1), "plan.txt", b"Low clearance overwrite.", clearance=1)
    assert resp.status_code == 409
    body = resp.json()
    assert set(body.keys()) == {"detail"}
    assert "3" not in body["detail"] and "SECRET_PLAN_TOKEN" not in body["detail"]
    after = [(c.chunk_id, c.text, c.metadata["clearance"]) for c in _doc_chunks(store, "acme", "plan.txt")]
    assert after == before


def test_replace_allowed_at_equal_clearance_and_for_admin(client, sample_store):
    _, store, _, _ = sample_store
    assert _upload(client, _acme_user(clearance=3), "plan.txt", b"Version one.", clearance=3).status_code == 200
    assert _upload(client, _acme_user(clearance=3), "plan.txt", b"Version two.", clearance=2).status_code == 200
    assert _upload(client, _acme_user(clearance=2), "plan.txt", b"Version three.", clearance=2).status_code == 200
    # Raise it above every analyst, then an admin can still replace it.
    store_text = lambda: " ".join(c.text for c in _doc_chunks(store, "acme", "plan.txt"))
    admin = _admin_user()
    assert _upload(client, admin, "plan.txt", b"Admin version.", clearance=5).status_code == 200
    assert _upload(client, _acme_user(clearance=2), "plan.txt", b"Nope.", clearance=1).status_code == 409
    assert _upload(client, admin, "plan.txt", b"Admin replaced again.", clearance=1).status_code == 200
    assert store_text() == "Admin replaced again."


def test_shorter_replacement_leaves_no_old_chunks(client, sample_store):
    _, store, _, _ = sample_store
    long_text = " ".join(f"Paragraph {i} mentions OLD_VERSION_TOKEN in detail." for i in range(300))
    first = _upload(client, _acme_user(), "report.txt", long_text.encode())
    assert first.status_code == 200
    assert first.json()["chunks_ingested"] > 1

    second = _upload(client, _acme_user(), "report.txt", b"Short NEW_VERSION_TOKEN summary.")
    assert second.status_code == 200
    doc = _doc_chunks(store, "acme", "report.txt")
    assert len(doc) == 1
    assert not any("OLD_VERSION_TOKEN" in c.text for c in store.all_chunks())

    resp = client.post(
        "/query", json={"question": "OLD_VERSION_TOKEN details", "engagement": "acme"},
        headers=_bearer(_acme_user()),
    )
    assert "OLD_VERSION_TOKEN" not in resp.json()["answer"]


def test_failed_replacement_keeps_old_version(client, sample_store, monkeypatch):
    _, store, _, pipeline = sample_store
    assert _upload(client, _acme_user(), "report.txt", b"Original KEEP_ME_TOKEN text.").status_code == 200
    before = [(c.chunk_id, c.text) for c in _doc_chunks(store, "acme", "report.txt")]

    # 1) The new version can't be read at all.
    assert _upload(client, _acme_user(), "report.pdf", b"not a pdf").status_code == 422
    # 2) The new version has no text.
    assert _upload(client, _acme_user(), "report.txt", b"   ").status_code == 422
    # 3) The store itself fails mid-replacement.
    def failing_replace(*args, **kwargs):
        raise RuntimeError("store failure")
    monkeypatch.setattr(store, "replace_document", failing_replace)
    with pytest.raises(RuntimeError):
        _upload(client, _acme_user(), "report.txt", b"Replacement that never lands.")
    monkeypatch.undo()

    after = [(c.chunk_id, c.text) for c in _doc_chunks(store, "acme", "report.txt")]
    assert after == before


def test_numpy_replace_document_failure_leaves_store_unchanged(sample_store):
    _, store, _, _ = sample_store
    snapshot = [c.chunk_id for c in store.all_chunks()]
    bad_vectors = np.zeros((2, store.dim), dtype=np.float32)  # 2 vectors, 1 chunk
    with pytest.raises(ValueError):
        store.replace_document("acme", "acme.txt", bad_vectors,
                               [StoredChunk("upload://acme/acme.txt#0::0", "x", {})])
    assert [c.chunk_id for c in store.all_chunks()] == snapshot


def test_same_filename_in_two_engagements_stays_separate(client, sample_store):
    _, store, _, _ = sample_store
    admin = _admin_user()
    assert _upload(client, admin, "report.txt", b"ACME_REPORT_TOKEN body.", engagement="acme").status_code == 200
    assert _upload(client, admin, "report.txt", b"GLOBEX_REPORT_TOKEN body.", engagement="globex").status_code == 200

    acme_doc = _doc_chunks(store, "acme", "report.txt")
    globex_doc = _doc_chunks(store, "globex", "report.txt")
    assert [c.text for c in acme_doc] == ["ACME_REPORT_TOKEN body."]
    assert [c.text for c in globex_doc] == ["GLOBEX_REPORT_TOKEN body."]
    assert not {c.chunk_id for c in acme_doc} & {c.chunk_id for c in globex_doc}

    # Re-uploading in acme replaces only acme's copy.
    assert _upload(client, admin, "report.txt", b"ACME_V2_TOKEN body.", engagement="acme").status_code == 200
    assert [c.text for c in _doc_chunks(store, "globex", "report.txt")] == ["GLOBEX_REPORT_TOKEN body."]

    # And an acme analyst never retrieves globex's copy.
    resp = client.post(
        "/query", json={"question": "report body token"}, headers=_bearer(_acme_user()),
    )
    assert "GLOBEX_REPORT_TOKEN" not in resp.json()["answer"]
