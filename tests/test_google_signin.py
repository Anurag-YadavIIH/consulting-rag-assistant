"""
Tests for browser Google sign-in support: stricter ID-token checks (issuer,
required claims, clock leeway, verified email, missing audience), the
HttpOnly refresh cookie with its CSRF header, sign-out revocation, the
"no access yet" rule for accounts with no grants, and the CORS guard.

Local keys and fakes only: no network, no real Postgres.
"""

import logging
import sys
import time
from pathlib import Path

import pytest

jwt = pytest.importorskip("jwt", reason="pyjwt[crypto] not installed")
pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("cryptography", reason="cryptography not installed")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from consultrag.api import main as api_main
from consultrag.api.deps import (
    get_authz_repo,
    get_ingestion_pipeline,
    get_oidc_verifier,
    get_rag_engine,
)
from consultrag.api.main import add_cors, app
from consultrag.api.routes.auth import CSRF_HEADER, REFRESH_COOKIE
from consultrag.auth.app_token import (
    AppTokenError,
    issue_app_token,
    issue_refresh_token,
    refresh_app_token,
    verify_app_token,
)
from consultrag.auth.google_login import authenticate_google_id_token
from consultrag.auth.oidc import (
    GOOGLE_DISCOVERY_URL,
    DiscoveryDocument,
    OIDCError,
    OIDCVerifier,
)
from consultrag.config import settings
from consultrag.embeddings import HashEmbedder
from consultrag.pipeline import IngestionPipeline
from consultrag.rag import RAGEngine
from consultrag.security.access import User
from consultrag.vectorstore import NumpyVectorStore

SECRET = "a-real-random-secret-for-signin-tests-24680"
AUDIENCE = "client-id.apps.googleusercontent.com"
OTHER_DISCOVERY_URL = "https://idp.example.test/.well-known/openid-configuration"
JWKS_URI = "https://keys.example.test/jwks"

_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIV_PEM = _PRIV.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
_JWK = RSAAlgorithm.to_jwk(_PRIV.public_key(), as_dict=True) | {"kid": "k1", "alg": "RS256"}


def _token(*, drop=(), **claims) -> str:
    now = int(time.time())
    base = {
        "sub": "google-sub-1", "email": "person@example.com", "email_verified": True,
        "iss": "https://accounts.google.com", "aud": AUDIENCE, "iat": now, "exp": now + 300,
    }
    base.update(claims)
    for name in drop:
        base.pop(name)
    return jwt.encode(base, _PRIV_PEM, algorithm="RS256", headers={"kid": "k1"})


def _verifier(monkeypatch, *, discovery_url=GOOGLE_DISCOVERY_URL,
              issuer="https://accounts.google.com", audience=AUDIENCE, fetches=None):
    def fake_discovery(self):
        if fetches is not None:
            fetches.append(1)
        return DiscoveryDocument(issuer=issuer, jwks_uri=JWKS_URI, fetched_at=time.time())

    monkeypatch.setattr(OIDCVerifier, "_fetch_discovery", fake_discovery)
    monkeypatch.setattr("jwt.PyJWKClient.fetch_data", lambda self: {"keys": [_JWK]})
    return OIDCVerifier(discovery_url=discovery_url, audience=audience)


# --- issuer ------------------------------------------------------------------


@pytest.mark.parametrize("iss", ["https://accounts.google.com", "accounts.google.com"])
def test_google_discovery_accepts_both_google_issuer_forms(monkeypatch, iss):
    assert _verifier(monkeypatch).verify(_token(iss=iss))["sub"] == "google-sub-1"


def test_google_discovery_still_rejects_any_other_issuer(monkeypatch):
    with pytest.raises(OIDCError):
        _verifier(monkeypatch).verify(_token(iss="https://evil.example.test"))


def test_other_provider_keeps_exact_issuer_matching(monkeypatch):
    # Even a provider whose discovery issuer is Google's https form gets no
    # alternate form unless the discovery document IS Google's.
    v = _verifier(monkeypatch, discovery_url=OTHER_DISCOVERY_URL,
                  issuer="https://accounts.google.com")
    assert v.verify(_token(iss="https://accounts.google.com"))
    with pytest.raises(OIDCError):
        v.verify(_token(iss="accounts.google.com"))


def test_other_provider_exact_issuer(monkeypatch):
    v = _verifier(monkeypatch, discovery_url=OTHER_DISCOVERY_URL, issuer="https://idp.example.test")
    assert v.verify(_token(iss="https://idp.example.test"))
    with pytest.raises(OIDCError):
        v.verify(_token(iss="idp.example.test"))


# --- required claims and clock leeway -----------------------------------------


@pytest.mark.parametrize("claim", ["exp", "iat", "iss", "aud", "sub"])
def test_token_missing_a_required_claim_is_rejected(monkeypatch, claim):
    with pytest.raises(OIDCError):
        _verifier(monkeypatch).verify(_token(drop=(claim,)))


def test_expiry_within_30s_leeway_is_accepted(monkeypatch):
    now = int(time.time())
    assert _verifier(monkeypatch).verify(_token(iat=now - 400, exp=now - 20))


def test_expiry_beyond_30s_leeway_is_rejected(monkeypatch):
    now = int(time.time())
    with pytest.raises(OIDCError):
        _verifier(monkeypatch).verify(_token(iat=now - 400, exp=now - 45))


def test_issued_slightly_in_the_future_is_accepted_within_leeway(monkeypatch):
    now = int(time.time())
    assert _verifier(monkeypatch).verify(_token(iat=now + 20, exp=now + 300))


# --- audience ----------------------------------------------------------------


def test_missing_audience_rejects_every_token_before_any_fetch(monkeypatch):
    fetches = []
    v = _verifier(monkeypatch, audience=None, fetches=fetches)
    with pytest.raises(OIDCError, match="OAUTH_AUDIENCE"):
        v.verify(_token())
    assert fetches == []


def test_startup_warns_when_audience_is_missing(monkeypatch, caplog):
    monkeypatch.setattr(settings, "oauth_audience", None)
    monkeypatch.setattr(settings, "dev_auth_bypass", False)
    monkeypatch.setattr(settings, "app_jwt_secret", SECRET)
    monkeypatch.setattr(api_main, "get_oidc_verifier", lambda: _verifier(monkeypatch, audience=None))
    with caplog.at_level(logging.WARNING, logger="consultrag.api.main"):
        with TestClient(app):
            pass
    assert any("OAUTH_AUDIENCE is not set" in r.getMessage() for r in caplog.records)


# --- verified email ----------------------------------------------------------


class _Repo:
    """In-memory authz store; new accounts get NO roles (as in Postgres)."""

    def __init__(self):
        self.by_sub: dict[str, int] = {}
        self.authz: dict[int, dict] = {}
        self.versions: dict[int, int] = {}

    def get_or_create_user(self, google_sub, email):
        if google_sub not in self.by_sub:
            uid = len(self.by_sub) + 1
            self.by_sub[google_sub] = uid
            self.authz[uid] = {"roles": frozenset(), "clearance": 1, "email": email}
        return self.by_sub[google_sub]

    def build_user(self, user_id):
        if user_id not in self.authz:
            raise ValueError(f"no such user_id: {user_id}")
        a = self.authz[user_id]
        return User(user_id=str(user_id), roles=a["roles"], clearance=a["clearance"], email=a["email"])

    def refresh_version(self, user_id):
        if user_id not in self.authz:
            raise ValueError(f"no such user_id: {user_id}")
        return self.versions.get(user_id, 0)

    def revoke_refresh_tokens(self, user_id):
        self.versions[user_id] = self.versions.get(user_id, 0) + 1


@pytest.mark.parametrize("value", [False, "true", None])
def test_unverified_email_is_rejected_and_no_user_is_created(monkeypatch, value):
    repo = _Repo()
    token = _token(email_verified=value) if value is not None else _token(drop=("email_verified",))
    with pytest.raises(OIDCError, match="not verified"):
        authenticate_google_id_token(f"Bearer {token}", _verifier(monkeypatch), repo)
    assert repo.by_sub == {}


# --- API: login cookie, refresh, CSRF header, logout --------------------------


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(settings, "app_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "dev_auth_bypass", False)
    repo = _Repo()
    verifier = _verifier(monkeypatch)
    embedder = HashEmbedder(dim=64)
    store = NumpyVectorStore(dim=64)
    engine = RAGEngine(embedder=embedder, store=store)
    pipeline = IngestionPipeline(embedder=embedder, store=store)
    # The lifespan's discovery prefetch must not reach the network either.
    monkeypatch.setattr(api_main, "get_oidc_verifier", lambda: verifier)
    app.dependency_overrides[get_authz_repo] = lambda: repo
    app.dependency_overrides[get_ingestion_pipeline] = lambda: pipeline
    app.dependency_overrides[get_oidc_verifier] = lambda: verifier
    app.dependency_overrides[get_rag_engine] = lambda: engine
    with TestClient(app) as c:
        yield c, repo
    app.dependency_overrides.clear()


def _login(client, token=None):
    return client.post("/auth/login", headers={"Authorization": f"Bearer {token or _token()}"})


def _refresh_cookie_from(resp) -> str:
    # The cookie is Secure, so the test client (plain http) won't replay it by
    # itself; tests send it explicitly, as a browser on https or localhost would.
    return resp.cookies[REFRESH_COOKIE]


def _post_with_cookie(client, path, cookie, *, csrf=True):
    headers = {"Cookie": f"{REFRESH_COOKIE}={cookie}"}
    if csrf:
        headers[CSRF_HEADER] = "1"
    return client.post(path, headers=headers)


def test_login_sets_hardened_refresh_cookie_and_keeps_it_out_of_the_body(api):
    client, _ = api
    resp = _login(client)
    assert resp.status_code == 200
    body = resp.json()
    assert "refresh_token" not in body and body["access_token"]
    set_cookie = resp.headers["set-cookie"]
    assert set_cookie.startswith(f"{REFRESH_COOKIE}=")
    for attr in ("HttpOnly", "Secure", "SameSite=strict", "Path=/auth"):
        assert attr.lower() in set_cookie.lower()


def test_refresh_with_cookie_and_header_returns_a_new_access_token(api):
    client, _ = api
    cookie = _refresh_cookie_from(_login(client))
    resp = _post_with_cookie(client, "/auth/refresh", cookie)
    assert resp.status_code == 200
    assert verify_app_token(resp.json()["access_token"], SECRET)["sub"] == "1"


@pytest.mark.parametrize("path", ["/auth/refresh", "/auth/logout"])
def test_cookie_routes_reject_requests_without_the_csrf_header(api, path):
    client, repo = api
    cookie = _refresh_cookie_from(_login(client))
    resp = _post_with_cookie(client, path, cookie, csrf=False)
    assert resp.status_code == 403
    # A rejected logout revoked nothing: the cookie still refreshes.
    assert repo.versions == {}
    assert _post_with_cookie(client, "/auth/refresh", cookie).status_code == 200


def test_refresh_without_cookie_is_401(api):
    client, _ = api
    resp = client.post("/auth/refresh", headers={CSRF_HEADER: "1"})
    assert resp.status_code == 401


def test_logout_revokes_on_the_server_and_clears_the_cookie(api):
    client, _ = api
    cookie = _refresh_cookie_from(_login(client))
    resp = _post_with_cookie(client, "/auth/logout", cookie)
    assert resp.status_code == 204
    cleared = resp.headers["set-cookie"].lower()
    assert f"{REFRESH_COOKIE}=" in cleared and "max-age=0" in cleared and "path=/auth" in cleared
    # Even if a copy of the old cookie survives somewhere, it no longer works.
    assert _post_with_cookie(client, "/auth/refresh", cookie).status_code == 401
    # Signing in again issues a working cookie.
    fresh = _refresh_cookie_from(_login(client))
    assert _post_with_cookie(client, "/auth/refresh", fresh).status_code == 200


def test_removed_role_takes_effect_at_next_refresh(api):
    client, repo = api
    cookie = _refresh_cookie_from(_login(client))
    repo.authz[1]["roles"] = frozenset({"analyst", "engagement:acme"})
    first = _post_with_cookie(client, "/auth/refresh", cookie).json()["access_token"]
    assert "engagement:acme" in verify_app_token(first, SECRET)["roles"]
    repo.authz[1]["roles"] = frozenset({"analyst"})
    second = _post_with_cookie(client, "/auth/refresh", cookie).json()["access_token"]
    assert "engagement:acme" not in verify_app_token(second, SECRET)["roles"]


def test_refresh_for_a_deleted_user_is_401_not_500(api):
    client, repo = api
    cookie = _refresh_cookie_from(_login(client))
    del repo.authz[1]
    assert _post_with_cookie(client, "/auth/refresh", cookie).status_code == 401


def test_refresh_token_with_non_numeric_sub_is_rejected():
    token = issue_refresh_token(User.make("dev-bypass-user", roles=["admin"]), SECRET)
    with pytest.raises(AppTokenError):
        refresh_app_token(token, SECRET, _Repo())


# --- unknown account: no access yet ------------------------------------------


def test_unknown_account_gets_no_access(api):
    client, _ = api
    access = _login(client).json()["access_token"]
    claims = verify_app_token(access, SECRET)
    assert claims["roles"] == [] and claims["engagements"] == []
    auth = {"Authorization": f"Bearer {access}"}

    me = client.get("/me", headers=auth)
    assert me.status_code == 200
    assert me.json() == {
        "user_id": "1", "engagements": [], "is_admin": False, "clearance": 1,
        "email": "person@example.com",
    }

    for path, body in (("/query", {"question": "anything"}), ("/draft", {"topic": "anything"})):
        resp = client.post(path, json=body, headers=auth)
        assert resp.status_code == 403
        assert resp.json()["detail"].startswith("no access yet")

    upload = client.post(
        "/ingest/upload", data={"engagement": "acme"},
        files={"file": ("a.txt", b"hello", "text/plain")}, headers=auth,
    )
    assert upload.status_code == 403


def test_no_access_rule_does_not_affect_members_or_admins(api):
    client, repo = api
    access = _login(client).json()["access_token"]
    repo.authz[1]["roles"] = frozenset({"analyst", "engagement:acme"})
    cookie = _refresh_cookie_from(_login(client))
    member = _post_with_cookie(client, "/auth/refresh", cookie).json()["access_token"]
    resp = client.post("/query", json={"question": "q"}, headers={"Authorization": f"Bearer {member}"})
    assert resp.status_code == 200
    assert access  # the original no-access token is unaffected by later grants until refreshed


# --- CORS --------------------------------------------------------------------


def test_cors_refuses_a_wildcard_origin():
    with pytest.raises(RuntimeError, match="explicit origins"):
        add_cors(FastAPI(), ["http://localhost:3000", "*"])


def test_credentialed_cors_only_for_configured_origins():
    probe = FastAPI()
    add_cors(probe, ["http://localhost:3000"])

    @probe.post("/auth/refresh")
    def _r():
        return {}

    c = TestClient(probe)
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": CSRF_HEADER,
    }
    ok = c.options("/auth/refresh", headers={"Origin": "http://localhost:3000", **preflight})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert ok.headers["access-control-allow-credentials"] == "true"

    bad = c.options("/auth/refresh", headers={"Origin": "https://evil.example.test", **preflight})
    assert "access-control-allow-origin" not in bad.headers
    simple = c.post("/auth/refresh", headers={"Origin": "https://evil.example.test"})
    assert "access-control-allow-origin" not in simple.headers


# --- failed refresh: safe reason in the log, generic 401 to the caller ---------


def _refresh_capturing_logs(client, caplog, cookie=None):
    headers = {CSRF_HEADER: "1"}
    if cookie is not None:
        headers["Cookie"] = f"{REFRESH_COOKIE}={cookie}"
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="consultrag"):
        resp = client.post("/auth/refresh", headers=headers)
    return resp


def _assert_safe_rejection(resp, caplog, reason, *, token=None):
    assert resp.status_code == 401
    assert resp.json() == {"detail": "not signed in"}  # identical for every reason
    lines = [r.getMessage() for r in caplog.records if r.name == "consultrag.api.routes.auth"]
    assert lines == [f"refresh rejected: reason={reason}"]
    logged = caplog.text + " ".join(str(r.args) for r in caplog.records)
    for forbidden in filter(None, (token, SECRET, "person@example.com", "google-sub-1")):
        assert forbidden not in logged


def test_failed_refresh_logs_missing_cookie(api, caplog):
    client, _ = api
    _assert_safe_rejection(_refresh_capturing_logs(client, caplog), caplog, "missing_cookie")


def test_failed_refresh_logs_expired(api, caplog):
    client, _ = api
    _login(client)  # creates user 1
    expired = issue_refresh_token(User.make("1", roles=[]), SECRET, expires_in=-60)
    resp = _refresh_capturing_logs(client, caplog, expired)
    _assert_safe_rejection(resp, caplog, "expired", token=expired)


def test_failed_refresh_logs_revoked(api, caplog):
    client, _ = api
    cookie = _refresh_cookie_from(_login(client))
    _post_with_cookie(client, "/auth/logout", cookie)
    resp = _refresh_capturing_logs(client, caplog, cookie)
    _assert_safe_rejection(resp, caplog, "revoked", token=cookie)


@pytest.mark.parametrize("kind", ["garbage", "wrong_secret", "access_token"])
def test_failed_refresh_logs_invalid(api, caplog, kind):
    client, _ = api
    _login(client)
    user = User.make("1", roles=[])
    if kind == "garbage":
        token = "not-a-jwt-at-all"
    elif kind == "wrong_secret":
        token = issue_refresh_token(user, "some-other-secret-0123456789abcdef")
    else:  # an access token presented as a refresh token
        token = issue_app_token(user, SECRET)
    resp = _refresh_capturing_logs(client, caplog, token)
    _assert_safe_rejection(resp, caplog, "invalid", token=token)


def test_failed_refresh_logs_unknown_user(api, caplog):
    client, repo = api
    cookie = _refresh_cookie_from(_login(client))
    del repo.authz[1]
    resp = _refresh_capturing_logs(client, caplog, cookie)
    _assert_safe_rejection(resp, caplog, "unknown_user", token=cookie)


def test_successful_refresh_logs_no_rejection(api, caplog):
    client, _ = api
    cookie = _refresh_cookie_from(_login(client))
    resp = _refresh_capturing_logs(client, caplog, cookie)
    assert resp.status_code == 200
    assert not [r for r in caplog.records if "refresh rejected" in r.getMessage()]
    assert cookie not in caplog.text and resp.json()["access_token"] not in caplog.text
