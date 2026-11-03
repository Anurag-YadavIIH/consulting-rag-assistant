/** Team page pieces, presets and the role shown in the sidebar. */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import type { InvitationInfo, MemberInfo } from "../lib/api";
import { PRESETS, engagementRoleFor, roleLabel } from "../lib/team";
import { InvitationTable, InviteForm, MemberEditor, MemberTable } from "../components/team/TeamParts";
import { UserPanel } from "../components/UserPanel";

const html = (el: ReturnType<typeof createElement>) => renderToStaticMarkup(el);
afterEach(() => vi.unstubAllGlobals());

const member = (over: Partial<MemberInfo> = {}): MemberInfo => ({
  user_id: "7", email: "person@example.test", clearance: 2, is_admin: false,
  engagements: [{ engagement: "acme", role: "manager" }], preset: "manager", has_access: true, ...over,
});

it("presets are only clearance (and admin) shortcuts", () => {
  expect(PRESETS.analyst).toEqual({ label: "Analyst", clearance: 1, isAdmin: false });
  expect(PRESETS.manager.clearance).toBe(2);
  expect(PRESETS.senior_management.clearance).toBe(3);
  expect(PRESETS.admin.isAdmin).toBe(true);
  expect(engagementRoleFor("admin")).toBe("senior_management"); // never "admin" on an engagement
});

it("role labels come from admin and clearance", () => {
  expect(roleLabel(true, 1)).toBe("Admin");
  expect(roleLabel(false, 1)).toBe("Analyst");
  expect(roleLabel(false, 2)).toBe("Manager");
  expect(roleLabel(false, 3)).toBe("Senior management");
  expect(roleLabel(false, 5)).toBe("Clearance 5");
});

it("the sidebar shows the user's role and clearance", () => {
  const out = html(createElement(UserPanel, {
    meInfo: { user_id: "7", engagements: ["acme"], is_admin: false, clearance: 2, email: "p@example.test" }, dark: true,
  }));
  expect(out).toContain("Manager, clearance 2");
});

it("the members table marks you, hides Remove on your own row and escapes emails", () => {
  const out = html(createElement(MemberTable, {
    members: [member({ user_id: "1", email: "me@example.test", is_admin: true, clearance: 3, preset: "admin" }),
              member({ email: '<img src=x onerror="1">@x.test' }),
              member({ user_id: "9", email: "new@example.test", engagements: [], has_access: false, clearance: 1 })],
    currentUserId: "1", onEdit: () => {}, onRemove: () => {},
  }));
  expect(out).toContain("(you)");
  expect(out).not.toContain('aria-label="Remove access for me@example.test"');
  expect(out).toContain('aria-label="Edit access for me@example.test"');
  expect(out).toContain("No access");
  expect(out).not.toContain("<img");
});

it("pending invitations have a labelled Revoke button", () => {
  const inv: InvitationInfo = { id: 3, email: "guest@example.test", engagements: ["acme", "globex"], role: "manager",
    clearance: 2, is_admin: false, created_at: "2026-11-03T10:00:00+00:00", expires_at: "2026-11-17T10:00:00+00:00" };
  const out = html(createElement(InvitationTable, { invitations: [inv], onRevoke: () => {} }));
  expect(out).toContain('aria-label="Revoke invitation for guest@example.test"');
  expect(out).toContain("acme, globex");
  expect(html(createElement(InvitationTable, { invitations: [], onRevoke: () => {} }))).toContain("No pending invitations.");
});

it("the invite form explains presets and that no email is sent", () => {
  const out = html(createElement(InviteForm, { knownEngagements: ["acme"], busy: false, onInvite: () => {} }));
  expect(out).toContain("Google account email");
  expect(out).toContain("Analyst (clearance 1)");
  expect(out).toContain("No email is sent");
  expect(out).toMatch(/<button[^>]*disabled[^>]*>Create invitation/); // empty form can't submit
});

it("the editor won't let you remove your own admin access", () => {
  const out = html(createElement(MemberEditor, {
    member: member({ is_admin: true, clearance: 3 }), isSelf: true, knownEngagements: ["acme"], busy: false,
    onSave: () => {}, onCancel: () => {},
  }));
  expect(out).toMatch(/type="checkbox"[^>]*checked=""[^>]*disabled=""|type="checkbox"[^>]*disabled=""[^>]*checked=""/);
  expect(out).toContain("You can&#x27;t remove your own admin access");
  expect(out).toContain("within 15 minutes");
});

it("team client calls use the admin paths and handle an empty 204", async () => {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    return init.method === "DELETE" && url.includes("/invitations/")
      ? new Response(null, { status: 204 })
      : new Response(JSON.stringify({ members: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  const api = await import("../lib/api");
  await expect(api.revokeInvitation(5)).resolves.toBeUndefined();
  await api.updateMember("7", { clearance: 2 });
  expect(calls.map((c) => `${c.init.method} ${c.url.replace("http://localhost:8000", "")}`)).toEqual([
    "DELETE /admin/invitations/5",
    "PATCH /admin/members/7",
  ]);
});
