"""
App session token tests. Everything here is local crypto + an in-memory fake
authz repository — no network, no real Postgres needed.
"""

import sys
import time
from pathlib import Path

import pytest

jwt = pytest.importorskip("jwt", reason="pyjwt[crypto] not installed")
pytest.importorskip("cryptography", reason="cryptography not installed")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.auth.app_token import (
    AppTokenError,
    DEFAULT_ACCESS_TOKEN_TTL,
    ensure_app_jwt_secret_configured,
    issue_app_token,
    issue_refresh_token,
    login_with_google_id_token,
    refresh_app_token,
    verify_app_token,
)
from consultrag.auth.oidc import DiscoveryDocument, OIDCError, OIDCVerifier
from consultrag.security.access import User

SECRET = "a-real-random-secret-not-a-placeholder-12345"
ISSUER = "https://issuer.example.test"
JWKS_URI = "https://issuer.example.test/jwks"
AUDIENCE = "test-audience"


# --- shared fakes/helpers ----------------------------------------------------


class _FakeAuthzRepository:
    """In-memory authz store: mutable so tests can simulate a permission
    change happening between token issuance and a later refresh."""

    def __init__(self):
        self._next_id = 1
        self._by_sub: dict[str, int] = {}
        self._authz: dict[int, dict] = {}  # user_id -> {roles, engagements, clearance}

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

    def set_authz(self, user_id: int, *, roles: frozenset, clearance: int) -> None:
        self._authz[user_id] = {"roles": roles, "clearance": clearance}


def _gen_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_pem, private_key.public_key()


def _jwk(public_key, kid: str) -> dict:
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return jwk


def _make_google_style_token(private_pem, kid: str, *, sub="google-sub-abc", aud=AUDIENCE) -> str:
    now = int(time.time())
    claims = {
        "sub": sub, "email": "person@example.com", "iss": ISSUER, "aud": aud,
        "iat": now, "exp": now + 300,
    }
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})


def _oidc_verifier_for(monkeypatch, jwks: dict) -> OIDCVerifier:
    v = OIDCVerifier(discovery_url="https://issuer.example.test/.well-known/openid-configuration",
                      audience=AUDIENCE)
    monkeypatch.setattr(
        OIDCVerifier, "_fetch_discovery",
        lambda self: DiscoveryDocument(issuer=ISSUER, jwks_uri=JWKS_URI, fetched_at=time.time()),
    )
    monkeypatch.setattr("jwt.PyJWKClient.fetch_data", lambda self: jwks)
    return v


# --- issuance correctness ----------------------------------------------------


def test_login_issues_token_whose_claims_match_the_authz_store(monkeypatch):
    priv, pub = _gen_rsa_keypair()
    jwks = {"keys": [_jwk(pub, "key-a")]}
    verifier = _oidc_verifier_for(monkeypatch, jwks)
    repo = _FakeAuthzRepository()

    google_token = _make_google_style_token(priv, "key-a", sub="google-sub-xyz")
    pair = login_with_google_id_token(f"Bearer {google_token}", verifier, repo, SECRET)

    claims = verify_app_token(pair.access_token, SECRET, expected_type="access")
    user_id = repo._by_sub["google-sub-xyz"]
    authz = repo._authz[user_id]

    # Assert against the SOURCE OF TRUTH, not just "looks plausible".
    assert claims["sub"] == str(user_id)
    assert set(claims["roles"]) == set(authz["roles"])
    assert claims["clearance"] == authz["clearance"]


def test_sub_is_internal_user_id_not_google_sub(monkeypatch):
    priv, pub = _gen_rsa_keypair()
    jwks = {"keys": [_jwk(pub, "key-a")]}
    verifier = _oidc_verifier_for(monkeypatch, jwks)
    repo = _FakeAuthzRepository()

    google_sub = "google-sub-should-not-appear-in-token"
    google_token = _make_google_style_token(priv, "key-a", sub=google_sub)
    pair = login_with_google_id_token(f"Bearer {google_token}", verifier, repo, SECRET)

    claims = verify_app_token(pair.access_token, SECRET, expected_type="access")
    assert claims["sub"] != google_sub
    assert claims["sub"] == str(repo._by_sub[google_sub])
    assert claims["sub"].isdigit()  # the internal Postgres user_id, stringified


# --- algorithm/token-type separation -----------------------------------------


def test_app_token_is_rejected_by_the_oidc_verifier(monkeypatch):
    jwks = {"keys": []}
    verifier = _oidc_verifier_for(monkeypatch, jwks)
    user = User(user_id="1", roles=frozenset({"analyst"}), clearance=1)
    app_token = issue_app_token(user, SECRET)

    with pytest.raises(OIDCError):
        verifier.verify(app_token)


def test_google_token_is_rejected_by_the_app_token_verifier():
    priv, pub = _gen_rsa_keypair()
    google_token = _make_google_style_token(priv, "key-a")

    with pytest.raises(AppTokenError):
        verify_app_token(google_token, SECRET, expected_type="access")


# --- fail-closed APP_JWT_SECRET ---------------------------------------------


@pytest.mark.parametrize("bad_secret", [None, "", "changeme", "secret", "short"])
def test_fails_closed_on_unset_or_placeholder_secret(bad_secret):
    with pytest.raises(RuntimeError):
        ensure_app_jwt_secret_configured(bad_secret, dev_auth_bypass=False)


def test_does_not_raise_with_a_real_secret():
    ensure_app_jwt_secret_configured(SECRET, dev_auth_bypass=False)  # must not raise


def test_dev_auth_bypass_skips_the_secret_check():
    ensure_app_jwt_secret_configured(None, dev_auth_bypass=True)  # must not raise


# --- lifetime / expiry -------------------------------------------------------


def test_expired_access_token_is_rejected():
    user = User(user_id="1", roles=frozenset({"analyst"}), clearance=1)
    expired = issue_app_token(user, SECRET, expires_in=-1)
    with pytest.raises(AppTokenError):
        verify_app_token(expired, SECRET, expected_type="access")


def test_default_access_ttl_is_short():
    assert DEFAULT_ACCESS_TOKEN_TTL <= 900  # 15 minutes


# --- refresh flow -------------------------------------------------------------


def test_refresh_exchanges_valid_token_for_a_new_access_token():
    repo = _FakeAuthzRepository()
    user = User(user_id="1", roles=frozenset({"engagement:acme", "analyst"}), clearance=2)
    repo._authz[1] = {"roles": user.roles, "clearance": user.clearance}
    refresh_token = issue_refresh_token(user, SECRET)

    new_access = refresh_app_token(refresh_token, SECRET, repo)
    claims = verify_app_token(new_access, SECRET, expected_type="access")
    assert claims["sub"] == "1"
    assert claims["clearance"] == 2


def test_refresh_rereads_authz_store_not_stale_claims():
    repo = _FakeAuthzRepository()
    repo._authz[1] = {"roles": frozenset({"analyst"}), "clearance": 1}
    user = repo.build_user(1)
    refresh_token = issue_refresh_token(user, SECRET)

    # Permission change happens in the DB AFTER the refresh token was issued —
    # e.g. an admin revokes/changes this user's access.
    repo.set_authz(1, roles=frozenset({"admin"}), clearance=5)

    new_access = refresh_app_token(refresh_token, SECRET, repo)
    claims = verify_app_token(new_access, SECRET, expected_type="access")

    assert claims["clearance"] == 5
    assert claims["roles"] == ["admin"]
    assert "analyst" not in claims["roles"]


def test_expired_refresh_token_cannot_refresh():
    repo = _FakeAuthzRepository()
    repo._authz[1] = {"roles": frozenset({"analyst"}), "clearance": 1}
    user = repo.build_user(1)
    expired_refresh = issue_refresh_token(user, SECRET, expires_in=-1)

    with pytest.raises(AppTokenError):
        refresh_app_token(expired_refresh, SECRET, repo)


def test_access_token_cannot_be_used_as_a_refresh_token():
    repo = _FakeAuthzRepository()
    repo._authz[1] = {"roles": frozenset({"analyst"}), "clearance": 1}
    user = repo.build_user(1)
    access_token = issue_app_token(user, SECRET)

    with pytest.raises(AppTokenError):
        refresh_app_token(access_token, SECRET, repo)


def test_refresh_token_cannot_be_used_as_an_access_token():
    user = User(user_id="1", roles=frozenset({"analyst"}), clearance=1)
    refresh_token = issue_refresh_token(user, SECRET)

    with pytest.raises(AppTokenError):
        verify_app_token(refresh_token, SECRET, expected_type="access")
