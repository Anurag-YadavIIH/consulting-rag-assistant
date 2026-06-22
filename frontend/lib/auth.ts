/**
 * The ONLY function that changes when real Google sign-in replaces
 * DEV_AUTH_BYPASS. Dev bypass now (server-side — see
 * src/consultrag/auth/dev_bypass.py): the API needs no token at all, so
 * this returns {}. Real Google OIDC drops in HERE: read a stored app
 * access token (obtained from POST /auth/login) and return
 * { Authorization: `Bearer ${token}` }, refreshing via POST /auth/refresh
 * as needed. Nothing else in this app — not lib/api.ts, not any
 * component — should assume how auth works; every call site gets its
 * headers from this one function.
 */
export function getAuthHeaders(): Record<string, string> {
  return {};
}
