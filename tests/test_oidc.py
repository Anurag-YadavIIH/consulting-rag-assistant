"""
OIDC verification tests. Everything here uses locally-generated RSA keys and
locally-signed tokens — no network calls, so this runs identically in CI and
offline. The discovery-document HTTP fetch and the JWKS HTTP fetch are each
monkeypatched independently so tests can control issuer/jwks_uri and the
published key set precisely.
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

from consultrag.auth.oidc import (
    ALLOWED_ALGORITHMS,
    DiscoveryDocument,
    OIDCError,
    OIDCVerifier,
    extract_bearer_token,
)

ISSUER = "https://issuer.example.test"
JWKS_URI = "https://issuer.example.test/jwks"
AUDIENCE = "test-audience"


def _gen_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, private_key.public_key(), public_pem


def _jwk(public_key, kid: str) -> dict:
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return jwk


KEY_A_PRIV, KEY_A_PUB, KEY_A_PUB_PEM = _gen_rsa_keypair()
KEY_B_PRIV, KEY_B_PUB, KEY_B_PUB_PEM = _gen_rsa_keypair()
JWKS_WITH_A_ONLY = {"keys": [_jwk(KEY_A_PUB, "key-a")]}
JWKS_WITH_A_AND_B = {"keys": [_jwk(KEY_A_PUB, "key-a"), _jwk(KEY_B_PUB, "key-b")]}


def _make_token(private_pem, kid, *, claims=None, alg="RS256", header_extra=None):
    now = int(time.time())
    base_claims = {
        "sub": "user-123",
        "email": "person@example.com",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
    }
    if claims:
        base_claims.update(claims)
    headers = {"kid": kid}
    if header_extra:
        headers.update(header_extra)
    return jwt.encode(base_claims, private_pem, algorithm=alg, headers=headers)


def _verifier_with_jwks(monkeypatch, jwks: dict, *, discovery_calls: list | None = None,
                         jwks_calls: list | None = None) -> OIDCVerifier:
    v = OIDCVerifier(discovery_url="https://issuer.example.test/.well-known/openid-configuration",
                      audience=AUDIENCE)

    def fake_fetch_discovery(self):
        if discovery_calls is not None:
            discovery_calls.append(1)
        return DiscoveryDocument(issuer=ISSUER, jwks_uri=JWKS_URI, fetched_at=time.time())

    def fake_fetch_data(self):
        if jwks_calls is not None:
            jwks_calls.append(1)
        return jwks

    monkeypatch.setattr(OIDCVerifier, "_fetch_discovery", fake_fetch_discovery)
    monkeypatch.setattr("jwt.PyJWKClient.fetch_data", fake_fetch_data)
    return v


# --- happy path -------------------------------------------------------------


def test_verify_accepts_valid_token(monkeypatch):
    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    token = _make_token(KEY_A_PRIV, "key-a")
    claims = verifier.verify(token)
    assert claims["sub"] == "user-123"
    assert claims["email"] == "person@example.com"


def test_discovery_values_are_not_hardcoded_to_google(monkeypatch):
    # No _fetch_discovery patch here — patch the actual HTTP layer
    # (urllib.request.urlopen) to prove issuer/jwks_uri genuinely come from
    # whatever OAUTH_DISCOVERY_URL points at, not a Google-specific path.
    import io
    import json

    requested_urls = []

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=5):
        requested_urls.append(url)
        return _FakeResponse(json.dumps({"issuer": ISSUER, "jwks_uri": JWKS_URI}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("jwt.PyJWKClient.fetch_data", lambda self: JWKS_WITH_A_ONLY)

    custom_discovery_url = "https://my-own-idp.example/.well-known/openid-configuration"
    verifier = OIDCVerifier(discovery_url=custom_discovery_url, audience=AUDIENCE)
    token = _make_token(KEY_A_PRIV, "key-a")
    claims = verifier.verify(token)

    assert claims["sub"] == "user-123"
    assert requested_urls == [custom_discovery_url]


# --- rejection cases (each must surface as OIDCError -> 401 upstream) -------


def test_rejects_token_with_kid_not_in_jwks(monkeypatch):
    # key-b is never published — get_signing_key refetches once, still can't
    # find it, and raises.
    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    token = _make_token(KEY_B_PRIV, "key-b")
    with pytest.raises(OIDCError):
        verifier.verify(token)


def test_rejects_token_signed_by_wrong_key_despite_matching_kid(monkeypatch):
    # kid says "key-a" (a real, published key), but the token bytes were
    # actually signed with key-b's private key — proves we verify the
    # cryptographic signature, not just that *some* key exists for that kid.
    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    forged = _make_token(KEY_B_PRIV, "key-a")
    with pytest.raises(OIDCError):
        verifier.verify(forged)


def test_rejects_wrong_audience(monkeypatch):
    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    token = _make_token(KEY_A_PRIV, "key-a", claims={"aud": "someone-elses-audience"})
    with pytest.raises(OIDCError):
        verifier.verify(token)


def test_rejects_wrong_issuer(monkeypatch):
    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    token = _make_token(KEY_A_PRIV, "key-a", claims={"iss": "https://not-the-real-issuer.test"})
    with pytest.raises(OIDCError):
        verifier.verify(token)


def test_rejects_expired_token(monkeypatch):
    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    now = int(time.time())
    token = _make_token(KEY_A_PRIV, "key-a", claims={"iat": now - 7200, "exp": now - 3600})
    with pytest.raises(OIDCError):
        verifier.verify(token)


@pytest.mark.parametrize(
    "header_value",
    [None, "", "justatoken", "Token abc.def.ghi", "Bearer", "Bearer   "],
)
def test_extract_bearer_token_rejects_malformed_or_missing(header_value):
    with pytest.raises(OIDCError):
        extract_bearer_token(header_value)


def test_extract_bearer_token_accepts_well_formed_header():
    assert extract_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"


def test_rejects_alg_none_even_with_a_kid_matching_a_real_key(monkeypatch):
    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    now = int(time.time())
    claims = {
        "sub": "user-123", "email": "x@example.com", "iss": ISSUER, "aud": AUDIENCE,
        "iat": now, "exp": now + 300,
    }
    # alg=none forgery attempting to ride on a real, published kid.
    forged = jwt.encode(claims, None, algorithm="none", headers={"kid": "key-a"})
    with pytest.raises(OIDCError):
        verifier.verify(forged)


def _manual_hs256_token(secret_bytes: bytes, header: dict, payload: dict) -> str:
    # Hand-crafted, bypassing jwt.encode entirely: recent PyJWT refuses to
    # let prepare_key() use a PEM-formatted key as an HMAC secret, which is
    # exactly the attack this test needs to forge. A real attacker forging
    # this wouldn't go through our server's library's safety rails either —
    # they'd construct the bytes directly, same as this does.
    import base64
    import hashlib
    import hmac
    import json

    def b64url(data: bytes) -> bytes:
        return base64.urlsafe_b64encode(data).rstrip(b"=")

    signing_input = (
        b64url(json.dumps(header, separators=(",", ":")).encode())
        + b"."
        + b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = hmac.new(secret_bytes, signing_input, hashlib.sha256).digest()
    return (signing_input + b"." + b64url(signature)).decode()


def test_rejects_hs256_confusion_using_rsa_public_key_as_hmac_secret(monkeypatch):
    # Classic RS256->HS256 confusion: sign with HS256 using the RSA *public*
    # key (which is, by design, publicly known) as the HMAC secret, hoping a
    # verifier naively uses "whatever key matches kid" without also pinning
    # algorithms=. Our explicit algorithms=["RS256"] must block this.
    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    now = int(time.time())
    claims = {
        "sub": "user-123", "email": "x@example.com", "iss": ISSUER, "aud": AUDIENCE,
        "iat": now, "exp": now + 300,
    }
    forged = _manual_hs256_token(KEY_A_PUB_PEM, {"alg": "HS256", "typ": "JWT", "kid": "key-a"}, claims)
    with pytest.raises(OIDCError):
        verifier.verify(forged)


def test_allowed_algorithms_is_exactly_rs256():
    # Pin the module-level allowlist itself — guards against a future edit
    # accidentally widening it (e.g. adding "none" or "HS256" for "convenience").
    assert ALLOWED_ALGORITHMS == ["RS256"]


# --- JWKS caching / key rotation --------------------------------------------


def test_jwks_caches_and_only_refetches_on_rotation(monkeypatch):
    jwks_calls: list = []
    current_jwks = {"doc": JWKS_WITH_A_ONLY}

    verifier = OIDCVerifier(discovery_url="https://issuer.example.test/.well-known/openid-configuration",
                             audience=AUDIENCE)

    def fake_fetch_discovery(self):
        return DiscoveryDocument(issuer=ISSUER, jwks_uri=JWKS_URI, fetched_at=time.time())

    def fake_fetch_data(self):
        jwks_calls.append(1)
        return current_jwks["doc"]

    monkeypatch.setattr(OIDCVerifier, "_fetch_discovery", fake_fetch_discovery)
    monkeypatch.setattr("jwt.PyJWKClient.fetch_data", fake_fetch_data)

    # First verify with key-a: one fetch (cache miss -> populate).
    token_a = _make_token(KEY_A_PRIV, "key-a")
    verifier.verify(token_a)
    assert len(jwks_calls) == 1

    # Second verify with key-a again: cached, no refetch.
    verifier.verify(_make_token(KEY_A_PRIV, "key-a"))
    assert len(jwks_calls) == 1

    # Provider rotates in key-b. A token signed with key-b has a kid the
    # cached JWKS doesn't know about yet -> must trigger exactly one refetch,
    # after which it's found and accepted.
    current_jwks["doc"] = JWKS_WITH_A_AND_B
    token_b = _make_token(KEY_B_PRIV, "key-b")
    claims = verifier.verify(token_b)
    assert claims["sub"] == "user-123"
    assert len(jwks_calls) == 2


# --- composition with the Stage 1 authz store -------------------------------


class _FakeAuthzRepository:
    """In-memory stand-in for authz.repository.AuthzRepository — proves the
    google_login orchestration calls get_or_create_user/build_user correctly
    without needing a real Postgres connection for this unit test."""

    def __init__(self):
        self.users = {}  # google_sub -> user_id
        self.calls = []

    def get_or_create_user(self, google_sub: str, email: str) -> int:
        self.calls.append(("get_or_create_user", google_sub, email))
        if google_sub not in self.users:
            self.users[google_sub] = len(self.users) + 1
        return self.users[google_sub]

    def build_user(self, user_id: int):
        from consultrag.security.access import User

        self.calls.append(("build_user", user_id))
        return User(user_id=str(user_id), roles=frozenset({"analyst"}), clearance=2)


def test_authenticate_google_id_token_composes_oidc_and_authz(monkeypatch):
    from consultrag.auth.google_login import authenticate_google_id_token

    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    token = _make_token(KEY_A_PRIV, "key-a")
    fake_repo = _FakeAuthzRepository()

    user = authenticate_google_id_token(f"Bearer {token}", verifier, fake_repo)

    assert user.clearance == 2
    assert "analyst" in user.roles
    assert ("get_or_create_user", "user-123", "person@example.com") in fake_repo.calls


def test_authenticate_google_id_token_rejects_bad_token(monkeypatch):
    from consultrag.auth.google_login import authenticate_google_id_token

    verifier = _verifier_with_jwks(monkeypatch, JWKS_WITH_A_ONLY)
    fake_repo = _FakeAuthzRepository()

    with pytest.raises(OIDCError):
        authenticate_google_id_token("Bearer not-a-real-token", verifier, fake_repo)
    assert fake_repo.calls == []  # never reaches the authz store on auth failure
