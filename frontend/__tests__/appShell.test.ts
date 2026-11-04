/**
 * What the app shell renders in each auth state. Rendered to static HTML with
 * react-dom/server (as `next build` prerenders pages for the static export),
 * so no DOM library is needed. The key rule: page content renders only for a
 * signed-in account that has access.
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: unknown; className?: string }) =>
    createElement("a", { href, className }, children as never),
}));

import {
  AppShell,
  ShellView,
  engagementOptionsFor,
  hasNoAccess,
  loadSignedInState,
  pickEngagement,
  type ShellState,
} from "../components/AppShell";
import type { MeResponse } from "../lib/api";

const SECRET_CHILD = "PROTECTED_PAGE_CONTENT";
const child = createElement("div", null, SECRET_CHILD);

function view(state: ShellState): string {
  return renderToStaticMarkup(
    createElement(ShellView, {
      state,
      engagement: "acme",
      setEngagement: () => {},
      onCredential: () => {},
      onSignOut: () => {},
      children: child,
    })
  );
}

const member: MeResponse = {
  user_id: "3", engagements: ["acme"], is_admin: false, clearance: 1, email: "me@example.com",
};
const unknownAccount: MeResponse = {
  user_id: "4", engagements: [], is_admin: false, clearance: 1, email: "new@example.com",
};
const admin: MeResponse = { user_id: "5", engagements: [], is_admin: true, clearance: 3 };

it("the prerendered page (before any login or /me) contains no page content", () => {
  const html = renderToStaticMarkup(createElement(AppShell, null, child));
  expect(html).not.toContain(SECRET_CHILD);
  expect(html).toContain("Loading");
});

it("signed out: the sign-in screen, and no page content", () => {
  const html = view({ kind: "signedOut" });
  expect(html).toContain("Sign in with your Google account");
  expect(html).not.toContain(SECRET_CHILD);
});

it("a sign-in error is shown on the sign-in screen", () => {
  const html = view({ kind: "signedOut", error: "Sign-in failed. Please try again." });
  expect(html).toContain("Sign-in failed. Please try again.");
  expect(html).not.toContain(SECRET_CHILD);
});

it("an API error shows no page content", () => {
  expect(view({ kind: "error", error: new Error("boom") })).not.toContain(SECRET_CHILD);
});

it("an account with no access sees 'No access yet', a sign-out button, and no page content", () => {
  const html = view({ kind: "ready", meInfo: unknownAccount });
  expect(html).toContain("No access yet");
  expect(html).toContain("new@example.com");
  expect(html).toContain("Sign out");
  expect(html).not.toContain(SECRET_CHILD);
});

it("a member sees the page, their email and a sign-out button", () => {
  const html = view({ kind: "ready", meInfo: member });
  expect(html).toContain(SECRET_CHILD);
  expect(html).toContain("me@example.com");
  expect(html).toContain("Sign out");
});

it("hasNoAccess: only non-admins with no memberships", () => {
  expect(hasNoAccess(unknownAccount)).toBe(true);
  expect(hasNoAccess(member)).toBe(false);
  expect(hasNoAccess(admin)).toBe(false);
});

it("engagement options: memberships for members, never the fallback for non-admins", () => {
  expect(engagementOptionsFor(member)).toEqual(["acme"]);
  expect(engagementOptionsFor(unknownAccount)).toEqual([]);
});

it("admins get the admin list merged with their own memberships, sorted and de-duplicated", () => {
  const adminWithAcme = { ...admin, engagements: ["meridian", "acme"] };
  expect(engagementOptionsFor(adminWithAcme, ["globex", "acme", "kestrel"])).toEqual(["acme", "globex", "kestrel", "meridian"]);
  expect(engagementOptionsFor(admin, ["globex", "acme"])).toEqual(["acme", "globex"]);
  expect(engagementOptionsFor(admin)).toEqual([]); // no build-time fallback
  // A non-admin never gets engagements beyond their memberships, whatever is passed.
  expect(engagementOptionsFor(member, ["globex", "kestrel"])).toEqual(["acme"]);
});

it("the first available engagement is selected, and a still-offered choice is kept", () => {
  expect(pickEngagement(["acme", "globex"], undefined)).toBe("acme");
  expect(pickEngagement(["acme", "globex"], "globex")).toBe("globex");
  expect(pickEngagement(["acme", "globex"], "gone")).toBe("acme");
  expect(pickEngagement([], undefined)).toBeUndefined();
});

// --- loading /me and, for admins only, /admin/engagements ------------------------------

function stubApi(meBody: MeResponse, engagements: { status: number; body: unknown }) {
  const calls: string[] = [];
  const fetchMock = vi.fn(async (url: string) => {
    const path = new URL(url).pathname;
    calls.push(path);
    const json = (status: number, body: unknown) =>
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (path === "/me") return json(200, meBody);
    if (path === "/admin/engagements") return json(engagements.status, engagements.body);
    return json(404, { detail: "not stubbed" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

it("an admin with no memberships gets every engagement from /admin/engagements, first one selected", async () => {
  const calls = stubApi(admin, { status: 200, body: { engagements: ["globex", "acme"] } });
  const { state, engagement } = await loadSignedInState();
  expect(calls).toEqual(["/me", "/admin/engagements"]);
  expect(engagementOptionsFor(state.meInfo, state.allEngagements)).toEqual(["acme", "globex"]);
  expect(engagement).toBe("acme");
  const html = view(state);
  expect(html).toContain('id="engagement-select"');
  expect(html).toContain(">globex</option>");
  expect(html).not.toContain("NEXT_PUBLIC_FALLBACK_ENGAGEMENTS");
  vi.unstubAllGlobals();
});

it("non-admins only call /me, never the admin list", async () => {
  const calls = stubApi(member, { status: 200, body: { engagements: ["globex"] } });
  const { state, engagement } = await loadSignedInState();
  expect(calls).toEqual(["/me"]);
  expect(state.allEngagements).toBeUndefined();
  expect(engagement).toBe("acme");
  expect(view(state)).not.toContain(">globex</option>");
  vi.unstubAllGlobals();
});

it("a failed admin list shows an error with a retry, keeps own memberships, and the page still renders", async () => {
  stubApi({ ...admin, engagements: ["acme"] }, { status: 500, body: { detail: "boom" } });
  const { state, engagement } = await loadSignedInState();
  expect(state.engagementsError).toBeTruthy();
  expect(engagement).toBe("acme");
  const html = view(state);
  expect(html).toContain(SECRET_CHILD);
  expect(html).toContain('role="alert"');
  expect(html).toContain("Couldn&#x27;t load the full engagement list. Showing your own engagements only.");
  expect(html).toContain(">Try again</button>");
  expect(html).toContain(">acme</option>");
  vi.unstubAllGlobals();
});

it("a fresh deployment with no engagements points an admin to the Team page, not an environment variable", async () => {
  stubApi(admin, { status: 200, body: { engagements: [] } });
  const { state, engagement } = await loadSignedInState();
  expect(engagement).toBeUndefined();
  const html = view(state);
  expect(html).toContain("No engagements yet.");
  expect(html).toMatch(/<a href="\/team\/"[^>]*>Team page<\/a>/);
  expect(html).not.toContain("NEXT_PUBLIC");
  expect(html).not.toContain('role="alert"');
  vi.unstubAllGlobals();
});

// --- navigation ----------------------------------------------------------------

it("Activity is in the sidebar for admins only", async () => {
  const { navItemsFor } = await import("../components/AppShell");
  expect(navItemsFor(member).map((n) => n.label)).toEqual(["Ask", "Documents"]);
  expect(navItemsFor({ ...admin, engagements: ["acme"] }).map((n) => n.label)).toEqual([
    "Ask",
    "Documents",
    "Activity",
    "Team",
  ]);

  const memberHtml = view({ kind: "ready", meInfo: member });
  expect(memberHtml).not.toContain('href="/activity/"');
  expect(memberHtml).not.toContain('href="/team/"');
  expect(memberHtml).toContain('href="/documents/"');
  const adminHtml = view({ kind: "ready", meInfo: { ...admin, engagements: ["acme"] } });
  expect(adminHtml).toContain('href="/activity/"');
  expect(adminHtml).toContain('href="/team/"');
});

it("the sidebar has a labelled menu button for small screens", () => {
  const out = view({ kind: "ready", meInfo: member });
  expect(out).toContain('aria-controls="app-sidebar"');
  expect(out).toContain('aria-expanded="false"');
  expect(out).toContain('id="engagement-select"');
});
