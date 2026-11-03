/** The Activity placeholder and the /management redirect page. */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/activity/",
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: unknown }) =>
    createElement("a", { href }, children as never),
}));

import { MeContext } from "../lib/meContext";
import ActivityPage from "../app/activity/page";
import ManagementRedirect from "../app/management/page";

function withMe(isAdmin: boolean, el: ReturnType<typeof createElement>) {
  return renderToStaticMarkup(
    createElement(
      MeContext.Provider,
      {
        value: {
          meInfo: { user_id: "1", engagements: ["acme"], is_admin: isAdmin, clearance: 2 },
          engagementOptions: ["acme"],
          engagement: "acme",
          setEngagement: () => {},
        },
      },
      el
    )
  );
}

it("Activity is a labelled placeholder for admins, with no rows", () => {
  const out = withMe(true, createElement(ActivityPage));
  expect(out).toContain("Placeholder");
  expect(out).not.toContain("<table");
  expect(out).not.toContain("<li");
});

it("Activity tells non-admins it's for administrators", () => {
  const out = withMe(false, createElement(ActivityPage));
  expect(out).toContain("Admins only");
  expect(out).not.toContain("Placeholder");
});

it("/management offers a link to /activity/ while it redirects", () => {
  const out = renderToStaticMarkup(createElement(ManagementRedirect));
  expect(out).toContain('href="/activity/"');
});

it("Documents keeps every upload rule: two short lines plus a native disclosure", async () => {
  const { IngestPanel } = await import("../components/IngestPanel");
  const out = renderToStaticMarkup(createElement(IngestPanel, { engagement: "acme" }));
  expect(out).toContain("37,500 words");
  expect(out).toContain("redacted on the server before anything is stored");
  expect(out).toMatch(/<details[^>]*>\s*<summary[^>]*>How uploads work<\/summary>/);
  expect(out).toContain("filename is stored as-is");
  expect(out).toContain("replaces that document");
  expect(out).toContain('type="file"'); // the native input is still there
  expect(out).toContain('id="upload-file"');
});

it("the primary button keeps the disabled attribute and a muted accent look", async () => {
  const { Button } = await import("../components/ui/Button");
  const out = renderToStaticMarkup(createElement(Button, { disabled: true }, "Ask"));
  expect(out).toContain("disabled");
  expect(out).toContain("disabled:bg-accent-muted");
  expect(out).toContain("disabled:text-on-accent-muted");
});
