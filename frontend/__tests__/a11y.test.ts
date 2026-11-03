/**
 * Static accessibility checks on rendered markup (no browser): every form
 * control has a label, every button has an accessible name, no images
 * without alt text. Focus order, screen reader output and phone layout are
 * checked by hand (see the browser checklist).
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: unknown; className?: string }) =>
    createElement("a", { href, className }, children as never),
}));

import { IngestPanel } from "../components/IngestPanel";
import { ThemeControl } from "../components/ThemeControl";
import { SignInScreen } from "../components/SignInScreen";
import { InviteForm, MemberEditor } from "../components/team/TeamParts";
import { AskWorkspace } from "../components/ask/AskWorkspace";
import { EngagementSelector } from "../components/EngagementSelector";

/** True if the tag at `pos` sits inside an open <label>...</label>. */
function insideLabel(html: string, pos: number): boolean {
  const before = html.slice(0, pos);
  return before.lastIndexOf("<label") > before.lastIndexOf("</label>");
}

function check(html: string, name: string) {
  const ids = new Set([...html.matchAll(/<label[^>]*for="([^"]+)"/g)].map((m) => m[1]));
  for (const m of html.matchAll(/<(input|select|textarea)\b([^>]*)>/g)) {
    const attrs = m[2];
    if (/type="hidden"/.test(attrs)) continue;
    const id = attrs.match(/id="([^"]+)"/)?.[1];
    const labelled = (id !== undefined && ids.has(id)) || /aria-label="/.test(attrs) || insideLabel(html, m.index ?? 0);
    expect(labelled, `${name}: unlabelled ${m[0]}`).toBeTruthy();
  }
  for (const m of html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)) {
    const text = m[2].replace(/<[^>]+>/g, "").trim();
    expect(Boolean(text) || /aria-label="/.test(m[1]), `${name}: button without a name`).toBeTruthy();
  }
  expect(html, `${name}: <img> without alt`).not.toMatch(/<img(?![^>]*\balt=)[^>]*>/);
}

const member = {
  user_id: "7", email: "p@example.test", clearance: 2, is_admin: false,
  engagements: [{ engagement: "acme", role: "manager" as const }], preset: "manager", has_access: true,
};

it.each([
  ["IngestPanel", () => createElement(IngestPanel, { engagement: "acme" })],
  ["ThemeControl", () => createElement(ThemeControl)],
  ["SignInScreen", () => createElement(SignInScreen, { onCredential: () => {} })],
  ["InviteForm", () => createElement(InviteForm, { knownEngagements: ["acme"], busy: false, onInvite: () => {} })],
  ["MemberEditor", () => createElement(MemberEditor, { member, isSelf: false, knownEngagements: ["acme"], busy: false, onSave: () => {}, onCancel: () => {} })],
  ["AskWorkspace", () => createElement(AskWorkspace, { engagement: "acme" })],
  ["EngagementSelector", () => createElement(EngagementSelector, { options: ["acme", "globex"], value: "acme", onChange: () => {} })],
] as Array<[string, () => ReturnType<typeof createElement>]>)("%s: labelled controls and named buttons", (name, el) => {
  check(renderToStaticMarkup(el()), name);
});

it("the checker itself catches an unlabelled input and a nameless button", () => {
  expect(() => check('<input id="x" type="text">', "probe")).toThrow();
  expect(() => check("<button></button>", "probe")).toThrow();
  expect(() => check('<label for="x">X</label><input id="x"><button aria-label="Go"></button>', "probe")).not.toThrow();
});
