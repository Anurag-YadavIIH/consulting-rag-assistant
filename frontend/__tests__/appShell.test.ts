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
const admin: MeResponse = { user_id: "5", engagements: [], is_admin: true, clearance: 5 };

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
