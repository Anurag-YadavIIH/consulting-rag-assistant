/**
 * Everything about how this app authenticates lives here. lib/api.ts only
 * calls authFetch(); components only call the sign-in/sign-out functions
 * and onSignedOut(). Nothing else should assume how auth works.
 *
 * Flow:
 *   1. Google Identity Services (GIS) renders the sign-in button and hands
 *      back a Google ID token.
 *   2. loginWithGoogleCredential() sends it once to POST /auth/login. The API
 *      returns an app access token (kept in memory only, in this module) and
 *      sets the refresh token as an HttpOnly cookie that scripts can't read.
 *   3. authFetch() attaches the access token. On a 401 it refreshes once
 *      through POST /auth/refresh (the browser sends the cookie) and retries
 *      the request once. If that fails, listeners are told the user is
 *      signed out and the app returns to the sign-in screen.
 *   4. A page reload loses the in-memory access token; the first API call
 *      gets a 401 and recovers it through the same refresh.
 *
 * DEV_AUTH_BYPASS needs nothing here: with bypass on (development only,
 * enforced server-side) the API accepts requests with no token, so the
 * first call simply succeeds.
 *
 * Tokens are never logged or written to browser storage.
 */

import { API_BASE_URL, GOOGLE_CLIENT_ID } from "./config";

/** Must match CSRF_HEADER in src/consultrag/api/routes/auth.py. The cookie
 * routes reject requests without it. */
export const CSRF_HEADER = "X-ConsultRAG-CSRF";

const GIS_SCRIPT_SRC = "https://accounts.google.com/gsi/client";

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
const signedOutListeners = new Set<() => void>();

export class LoginError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "LoginError";
    this.status = status;
  }
}

export function getAuthHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

/** Subscribes to "the session has ended" (failed refresh or sign-out).
 * Returns an unsubscribe function. */
export function onSignedOut(listener: () => void): () => void {
  signedOutListeners.add(listener);
  return () => {
    signedOutListeners.delete(listener);
  };
}

function notifySignedOut(): void {
  accessToken = null;
  for (const listener of signedOutListeners) listener();
}

/** Exchanges a Google ID token for an app session. */
export async function loginWithGoogleCredential(idToken: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/auth/login`, {
      method: "POST",
      headers: { Authorization: `Bearer ${idToken}` },
      credentials: "include",
    });
  } catch {
    throw new LoginError(0, `Can't reach the API at ${API_BASE_URL}.`);
  }
  if (!res.ok) {
    // The API's detail can describe why verification failed; it never
    // contains the token itself.
    throw new LoginError(res.status, "Sign-in failed. Please try again.");
  }
  const body = (await res.json()) as { access_token: string };
  accessToken = body.access_token;
}

/** Gets a new access token using the refresh cookie. Concurrent callers
 * share one request. Resolves false (and clears the token) on failure. */
export function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
          method: "POST",
          headers: { [CSRF_HEADER]: "1" },
          credentials: "include",
        });
        if (!res.ok) {
          accessToken = null;
          return false;
        }
        const body = (await res.json()) as { access_token: string };
        accessToken = body.access_token;
        return true;
      } catch {
        accessToken = null;
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

/** fetch() with the access token attached. On a 401: one refresh, then one
 * retry. If the retry is still 401 (or the refresh fails), the session is
 * over: listeners are notified and the 401 response is returned. Network
 * failures reject exactly as fetch() does. */
export async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const send = () =>
    fetch(url, { ...init, headers: { ...(init.headers ?? {}), ...getAuthHeaders() } });

  const first = await send();
  if (first.status !== 401) return first;

  if (await refreshAccessToken()) {
    const retry = await send();
    if (retry.status !== 401) return retry;
    notifySignedOut();
    return retry;
  }
  notifySignedOut();
  return first;
}

/** Ends the session: the API revokes the refresh token on the server and
 * clears the cookie, the in-memory access token is dropped, and Google's
 * automatic re-selection is turned off. Always completes locally, even if
 * the API can't be reached. */
export async function signOut(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/auth/logout`, {
      method: "POST",
      headers: { [CSRF_HEADER]: "1" },
      credentials: "include",
    });
  } catch {
    // The local session still ends; the cookie expires on its own.
  }
  googleIdentity()?.disableAutoSelect();
  notifySignedOut();
}

// --- Google Identity Services --------------------------------------------

interface GoogleCredentialResponse {
  credential: string;
}

interface GoogleIdentity {
  initialize(config: {
    client_id: string;
    callback: (response: GoogleCredentialResponse) => void;
    auto_select?: boolean;
    ux_mode?: "popup" | "redirect";
  }): void;
  renderButton(parent: HTMLElement, options: Record<string, unknown>): void;
  disableAutoSelect(): void;
}

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleIdentity } };
  }
}

function googleIdentity(): GoogleIdentity | undefined {
  return typeof window === "undefined" ? undefined : window.google?.accounts?.id;
}

let gisLoading: Promise<GoogleIdentity> | null = null;

function loadGoogleIdentity(): Promise<GoogleIdentity> {
  const ready = googleIdentity();
  if (ready) return Promise.resolve(ready);
  if (!gisLoading) {
    gisLoading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = GIS_SCRIPT_SRC;
      script.async = true;
      script.onload = () => {
        const gis = googleIdentity();
        if (gis) resolve(gis);
        else reject(new Error("Google sign-in failed to initialise."));
      };
      script.onerror = () => {
        gisLoading = null;
        reject(new Error("Couldn't load Google sign-in. Check your connection."));
      };
      document.head.appendChild(script);
    });
  }
  return gisLoading;
}

export function isGoogleSignInConfigured(): boolean {
  return GOOGLE_CLIENT_ID !== "";
}

/** Renders the Google button into `parent`. `onCredential` receives the
 * Google ID token after the user picks an account. */
export async function renderGoogleSignInButton(
  parent: HTMLElement,
  onCredential: (idToken: string) => void
): Promise<void> {
  const gis = await loadGoogleIdentity();
  gis.initialize({
    client_id: GOOGLE_CLIENT_ID,
    callback: (response) => onCredential(response.credential),
    auto_select: false,
    ux_mode: "popup",
  });
  gis.renderButton(parent, { theme: "outline", size: "large", text: "signin_with" });
}

/** Test-only: resets module state between tests. */
export function __resetAuthForTests(): void {
  accessToken = null;
  refreshInFlight = null;
  signedOutListeners.clear();
}
