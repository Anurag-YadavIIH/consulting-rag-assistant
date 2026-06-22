"""
OIDC token verification — provider-agnostic, driven entirely by an OIDC
discovery document (config.settings.oauth_discovery_url). This module answers
WHO is making the request (a verified sub/email from a signed token). It
deliberately does NOT decide WHAT they can access — that's
authz/repository.py, backed by our own Postgres tables, never trusted from
token claims (a Google ID token only carries sub/email; app permissions must
not come from it).

Security notes:
  * algorithms= is always passed explicitly to jwt.decode. PyJWT rejects any
    token whose header `alg` isn't in that list BEFORE attempting signature
    verification — this is what blocks `alg=none` forgery and RS256/HS256
    algorithm-confusion attacks. Never omit it, never derive alg from the
    token itself.
  * The JWKS client caches keys (cache_keys=True) and, per PyJWT's
    PyJWKClient.get_signing_key, automatically refetches and retries once if
    a token's `kid` isn't found in the cached set — this is what makes key
    rotation transparent without restarting the process.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

# Only RS256 is accepted, explicitly. Restricting this list is the actual
# defense against alg=none and HS256-confusion forgeries — PyJWT checks the
# token header's alg against exactly this list.
ALLOWED_ALGORITHMS = ["RS256"]


class OIDCError(Exception):
    """Token failed authentication for any reason. Callers (the FastAPI
    dependency built in a later stage) should treat this uniformly as a 401
    rather than branching on the specific cause."""


@dataclass
class DiscoveryDocument:
    issuer: str
    jwks_uri: str
    fetched_at: float


class OIDCVerifier:
    """Verifies bearer tokens against any OIDC provider's discovery
    document. Nothing here is Google-specific — any compliant issuer works
    by pointing discovery_url at its own discovery document."""

    def __init__(self, discovery_url: str, audience: str, *, discovery_ttl_seconds: float = 3600):
        self.discovery_url = discovery_url
        self.audience = audience
        self.discovery_ttl_seconds = discovery_ttl_seconds
        self._discovery: DiscoveryDocument | None = None
        self._jwk_client: PyJWKClient | None = None

    def _fetch_discovery(self) -> DiscoveryDocument:
        import json
        import urllib.request

        with urllib.request.urlopen(self.discovery_url, timeout=5) as resp:
            doc = json.load(resp)
        return DiscoveryDocument(
            issuer=doc["issuer"], jwks_uri=doc["jwks_uri"], fetched_at=time.time()
        )

    def ensure_discovery(self, *, force: bool = False) -> DiscoveryDocument:
        """Fetches (or returns the cached) discovery document. The actual
        startup-time prefetch hook lives in the API app (later stage); this
        is the lazy-fetch-with-TTL-cache mechanism it calls."""
        stale = (
            self._discovery is None
            or force
            or (time.time() - self._discovery.fetched_at) > self.discovery_ttl_seconds
        )
        if stale:
            self._discovery = self._fetch_discovery()
            self._jwk_client = PyJWKClient(self._discovery.jwks_uri, cache_keys=True)
        return self._discovery

    def verify(self, token: str) -> dict:
        """Returns decoded claims (sub, email, ...) on success. Raises
        OIDCError on ANY failure: bad/forged signature, wrong issuer or
        audience, expiry, a disallowed algorithm, or a discovery/JWKS fetch
        problem."""
        discovery = self.ensure_discovery()
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self.audience,
                issuer=discovery.issuer,
            )
        except jwt.PyJWTError as e:
            raise OIDCError(str(e)) from e
        except Exception as e:  # JWKS fetch failures, malformed kid, etc.
            raise OIDCError(str(e)) from e
        return claims


def extract_bearer_token(authorization_header: str | None) -> str:
    """Parses 'Bearer <token>' out of a raw Authorization header value.
    Raises OIDCError on anything malformed or missing — same uniform
    401-shaped failure as verify()."""
    if not authorization_header:
        raise OIDCError("missing Authorization header")
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1].strip():
        raise OIDCError("Authorization header must be 'Bearer <token>'")
    return parts[1].strip()
