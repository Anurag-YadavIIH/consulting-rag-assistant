/**
 * lib/auth.ts: login, refresh-and-retry, failed refresh, sign-out. fetch is
 * mocked, fully offline. Requests are routed by URL so each test can script
 * the API's answers.
 */

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { me, NotAuthenticatedError } from "../lib/api";
import {
  CSRF_HEADER,
  LoginError,
  __resetAuthForTests,
  getAuthHeaders,
  loginWithGoogleCredential,
  onSignedOut,
  refreshAccessToken,
  signOut,
} from "../lib/auth";

const API = "http://localhost:8000";
const ME_BODY = { user_id: "3", engagements: ["acme"], is_admin: false, clearance: 1 };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type Call = { url: string; init: RequestInit };

/** Installs a fetch mock. `routes` maps a path to a list of responses
 * returned in order (the last one repeats). Returns the recorded calls. */
function mockApi(routes: Record<string, Array<() => Response>>): Call[] {
  const calls: Call[] = [];
  const counters: Record<string, number> = {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      const path = url.replace(API, "");
      const list = routes[path];
      if (!list) throw new Error(`unexpected request to ${path}`);
      const i = Math.min(counters[path] ?? 0, list.length - 1);
      counters[path] = (counters[path] ?? 0) + 1;
      return list[i]();
    })
  );
  return calls;
}

function headersOf(call: Call): Record<string, string> {
  return (call.init.headers ?? {}) as Record<string, string>;
}

const consoleSpies: Array<ReturnType<typeof vi.spyOn>> = [];

beforeEach(() => {
  __resetAuthForTests();
  for (const m of ["log", "info", "warn", "error", "debug"] as const) {
    consoleSpies.push(vi.spyOn(console, m).mockImplementation(() => {}));
  }
});

afterEach(() => {
  // Nothing in the auth flow may write to the console (tokens must never be
  // logged).
  for (const spy of consoleSpies) expect(spy).not.toHaveBeenCalled();
  consoleSpies.splice(0).forEach((s) => s.mockRestore());
  vi.unstubAllGlobals();
});

// --- login --------------------------------------------------------------------

it("login sends the Google ID token once and uses the returned access token", async () => {
  const calls = mockApi({
    "/auth/login": [() => json(200, { access_token: "app-access-1", token_type: "bearer" })],
    "/me": [() => json(200, ME_BODY)],
  });

  await loginWithGoogleCredential("google-id-token");
  expect(calls[0].init.method).toBe("POST");
  expect(headersOf(calls[0]).Authorization).toBe("Bearer google-id-token");
  expect(calls[0].init.credentials).toBe("include"); // lets the API set the cookie

  await expect(me()).resolves.toEqual(ME_BODY);
  expect(headersOf(calls[1]).Authorization).toBe("Bearer app-access-1");
});

it("a rejected login throws LoginError and keeps no token", async () => {
  mockApi({ "/auth/login": [() => json(401, { detail: "token email is not verified" })] });
  await expect(loginWithGoogleCredential("bad")).rejects.toBeInstanceOf(LoginError);
  expect(getAuthHeaders()).toEqual({});
});

// --- refresh ------------------------------------------------------------------

it("a 401 triggers one refresh via the cookie, then retries once with the new token", async () => {
  const calls = mockApi({
    "/me": [() => json(401, { detail: "expired" }), () => json(200, ME_BODY)],
    "/auth/refresh": [() => json(200, { access_token: "app-access-2" })],
  });

  await expect(me()).resolves.toEqual(ME_BODY);

  expect(calls.map((c) => c.url.replace(API, ""))).toEqual(["/me", "/auth/refresh", "/me"]);
  const refresh = calls[1];
  expect(refresh.init.credentials).toBe("include");
  expect(headersOf(refresh)[CSRF_HEADER]).toBe("1");
  expect(headersOf(calls[2]).Authorization).toBe("Bearer app-access-2");
});

it("concurrent 401s share a single refresh request", async () => {
  const calls = mockApi({
    "/me": [() => json(401, {}), () => json(401, {}), () => json(200, ME_BODY)],
    "/auth/refresh": [() => json(200, { access_token: "app-access-3" })],
  });
  await Promise.all([me(), me()]);
  expect(calls.filter((c) => c.url.endsWith("/auth/refresh"))).toHaveLength(1);
});

it("a page reload (no token in memory) recovers the session through refresh", async () => {
  // After a reload the module starts empty: the first call goes out with no
  // Authorization header.
  const calls = mockApi({
    "/me": [() => json(401, { detail: "missing Authorization header" }), () => json(200, ME_BODY)],
    "/auth/refresh": [() => json(200, { access_token: "after-reload" })],
  });
  await expect(me()).resolves.toEqual(ME_BODY);
  expect(headersOf(calls[0]).Authorization).toBeUndefined();
  expect(headersOf(calls[2]).Authorization).toBe("Bearer after-reload");
});

it("a failed refresh signs out, does not retry, and surfaces NotAuthenticatedError", async () => {
  const calls = mockApi({
    "/me": [() => json(401, { detail: "expired" })],
    "/auth/refresh": [() => json(401, { detail: "refresh token has been revoked" })],
  });
  const signedOut = vi.fn();
  onSignedOut(signedOut);

  await expect(me()).rejects.toBeInstanceOf(NotAuthenticatedError);
  expect(signedOut).toHaveBeenCalledTimes(1);
  expect(calls.map((c) => c.url.replace(API, ""))).toEqual(["/me", "/auth/refresh"]);
  expect(getAuthHeaders()).toEqual({});
});

it("a retry that is still 401 signs out instead of looping", async () => {
  const calls = mockApi({
    "/me": [() => json(401, {})],
    "/auth/refresh": [() => json(200, { access_token: "still-rejected" })],
  });
  const signedOut = vi.fn();
  onSignedOut(signedOut);
  await expect(me()).rejects.toBeInstanceOf(NotAuthenticatedError);
  expect(signedOut).toHaveBeenCalledTimes(1);
  expect(calls).toHaveLength(3);
});

it("a refresh that can't reach the API resolves false", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
  await expect(refreshAccessToken()).resolves.toBe(false);
});

// --- sign-out -----------------------------------------------------------------

it("sign-out revokes on the server, clears the token and notifies the app", async () => {
  const calls = mockApi({
    "/auth/login": [() => json(200, { access_token: "app-access-4" })],
    "/auth/logout": [() => new Response(null, { status: 204 })],
    "/me": [() => json(401, {})],
    "/auth/refresh": [() => json(401, {})],
  });
  const disableAutoSelect = vi.fn();
  vi.stubGlobal("window", { google: { accounts: { id: { disableAutoSelect } } } });
  const signedOut = vi.fn();
  onSignedOut(signedOut);

  await loginWithGoogleCredential("google-id-token");
  expect(getAuthHeaders()).toEqual({ Authorization: "Bearer app-access-4" });

  await signOut();
  const logout = calls.find((c) => c.url.endsWith("/auth/logout"))!;
  expect(logout.init.method).toBe("POST");
  expect(logout.init.credentials).toBe("include");
  expect(headersOf(logout)[CSRF_HEADER]).toBe("1");
  expect(getAuthHeaders()).toEqual({});
  expect(disableAutoSelect).toHaveBeenCalled();
  expect(signedOut).toHaveBeenCalled();

  // The next request carries no token.
  await expect(me()).rejects.toBeInstanceOf(NotAuthenticatedError);
  const meCall = calls.find((c) => c.url.endsWith("/me"))!;
  expect(headersOf(meCall).Authorization).toBeUndefined();
});

it("sign-out still ends the local session when the API is unreachable", async () => {
  mockApi({ "/auth/login": [() => json(200, { access_token: "app-access-5" })] });
  await loginWithGoogleCredential("google-id-token");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
  const signedOut = vi.fn();
  onSignedOut(signedOut);
  await signOut();
  expect(getAuthHeaders()).toEqual({});
  expect(signedOut).toHaveBeenCalled();
});

it("a sign-in refused by the domain rule (403) explains what to do", async () => {
  mockApi({ "/auth/login": [() => json(403, { detail: "this account isn't allowed to sign in here" })] });
  await expect(loginWithGoogleCredential("google-id-token")).rejects.toMatchObject({
    status: 403,
    message: expect.stringContaining("isn't allowed to sign in here"),
  });
  expect(getAuthHeaders()).toEqual({});
});
