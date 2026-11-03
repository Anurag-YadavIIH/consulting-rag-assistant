/**
 * API base URL handling, including the same-origin build used on AWS
 * (CloudFront serves the frontend and the API together), and the timeout
 * message users see when CloudFront gives up on a slow upload.
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { ServerError } from "../lib/api";
import { resolveApiBaseUrl } from "../lib/config";
import { ErrorBanner } from "../components/ErrorBanner";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.resetModules();
});

it("unset means the local development API", () => {
  expect(resolveApiBaseUrl(undefined)).toBe("http://localhost:8000");
});

it('"/" and "" both mean same origin (relative paths)', () => {
  expect(resolveApiBaseUrl("/")).toBe("");
  expect(resolveApiBaseUrl("")).toBe("");
});

it("trailing slashes are dropped from a full URL", () => {
  expect(resolveApiBaseUrl("https://example.test/")).toBe("https://example.test");
  expect(resolveApiBaseUrl("http://localhost:8000")).toBe("http://localhost:8000");
});

it('a "/" build calls the API on the same origin: fetch("/me")', async () => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "/");
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ user_id: "1", engagements: ["acme"], is_admin: false, clearance: 1 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  );
  vi.stubGlobal("fetch", fetchMock);
  const api = await import("../lib/api"); // fresh module, reads the stubbed env
  await api.me();
  expect(fetchMock.mock.calls[0][0]).toBe("/me");
});

it("a 504 (CloudFront timeout) explains the upload may still finish", () => {
  const html = renderToStaticMarkup(
    createElement(ErrorBanner, { error: new ServerError(504, "<html>gateway timeout</html>") })
  );
  expect(html).toContain("took too long to respond");
  expect(html).toContain("may still finish processing");
  expect(html).not.toContain("gateway timeout"); // never the raw CloudFront page
});

it("other 5xx errors keep the generic message", () => {
  const html = renderToStaticMarkup(createElement(ErrorBanner, { error: new ServerError(502, "bad") }));
  expect(html).toContain("Something went wrong on the server");
});
