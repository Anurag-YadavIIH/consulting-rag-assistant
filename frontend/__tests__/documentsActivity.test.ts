/** Documents list, activity table, confirmation dialog and sign-in page. */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import type { ActivityEvent, DocumentInfo } from "../lib/api";
import { DocumentList, formatUploaded } from "../components/documents/DocumentList";
import { ActivityTable, eventDetails, eventLabel } from "../components/activity/ActivityTable";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { SignInScreen } from "../components/SignInScreen";

const html = (el: ReturnType<typeof createElement>) => renderToStaticMarkup(el);
const doc = (over: Partial<DocumentInfo> = {}): DocumentInfo => ({
  name: "deck.pptx", chunks: 2, clearance: 1, uploaded_at: "2026-11-03T10:00:00+00:00", ...over,
});

// --- documents --------------------------------------------------------------------------

it("lists documents with a labelled delete button for each", () => {
  const out = html(createElement(DocumentList, {
    engagement: "acme", documents: [doc(), doc({ name: "notes.txt", chunks: 1, uploaded_at: null })],
    loading: false, onDelete: () => {},
  }));
  expect(out).toContain("<table");
  expect(out).toContain('aria-label="Delete deck.pptx"');
  expect(out).toContain('aria-label="Delete notes.txt"');
  expect(out).toContain("Not recorded"); // older documents have no upload time
  expect(out).toContain("Documents in acme");
});

it("shows an empty state, and a spinner while first loading", () => {
  expect(html(createElement(DocumentList, { engagement: "acme", documents: [], loading: false, onDelete: () => {} })))
    .toContain("No documents yet");
  expect(html(createElement(DocumentList, { engagement: "acme", documents: null, loading: true, onDelete: () => {} })))
    .toContain("Loading documents");
});

it("escapes hostile filenames in the list", () => {
  const out = html(createElement(DocumentList, {
    engagement: "acme", documents: [doc({ name: '<img src=x onerror="alert(1)">.pdf' })], loading: false, onDelete: () => {},
  }));
  expect(out).not.toContain("<img");
  expect(out).toContain("&lt;img");
});

it("formats upload times and handles missing or bad values", () => {
  expect(formatUploaded(null)).toBe("Not recorded");
  expect(formatUploaded("not a date")).toBe("Not recorded");
  expect(formatUploaded("2026-11-03T10:00:00+00:00")).not.toBe("Not recorded");
});

// --- activity ---------------------------------------------------------------------------

const ev = (over: Partial<ActivityEvent>): ActivityEvent => ({
  id: 1, ts: "2026-11-03T10:00:00+00:00", event: "ingest", user_id: "90", engagement: "acme",
  document: "deck.pptx", n_chunks: 2, redaction_counts: { EMAIL: 1 }, n_retrieved: null, n_blocked: null, ...over,
});

it("summarises events in plain language with no question text", () => {
  expect(eventLabel("ingest")).toBe("Upload");
  expect(eventLabel("query")).toBe("Question");
  expect(eventDetails(ev({}))).toBe("2 chunks, 1 item redacted");
  expect(eventDetails(ev({ event: "query", n_retrieved: 3, n_blocked: 1, n_chunks: null }))).toBe(
    "3 passages returned, 1 withheld by access rules"
  );
  expect(eventDetails(ev({ event: "delete", n_chunks: 1, redaction_counts: null }))).toBe("1 chunk");
});

it("renders activity rows by user number and escapes document names", () => {
  const out = html(createElement(ActivityTable, {
    events: [ev({}), ev({ id: 2, event: "delete", document: "<script>x</script>" })],
  }));
  expect(out.match(/<tr/g)?.length).toBe(3); // header + 2 rows
  expect(out).toContain(">90<");
  expect(out).not.toContain("<script>");
  expect(out).not.toMatch(/@/); // no emails anywhere
});

// --- confirmation and sign-in ---------------------------------------------------------------

it("the confirmation dialog has a title, a safe Cancel and the destructive action", () => {
  const out = html(createElement(ConfirmDialog, {
    open: true, title: "Delete this document?", confirmLabel: "Delete document",
    onConfirm: () => {}, onCancel: () => {}, children: "It goes for everyone.",
  }));
  expect(out).toContain("<dialog");
  expect(out).toContain('aria-labelledby="confirm-title"');
  expect(out).toContain(">Cancel<");
  expect(out).toContain("Delete document");
});

it("the sign-in page shows a plain headline and the three points", () => {
  const out = html(createElement(SignInScreen, { onCredential: () => {} }));
  const h1 = out.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)?.[1] ?? "";
  expect(h1.trim()).toBe("Find the answer. Keep client details private."); // no bar standing in for a word
  for (const t of ["Redacted first", "Separated by engagement", "Every passage cited"]) expect(out).toContain(t);
  expect(out).toContain("Sign in with your Google account to continue.");
});

it("the how-it-works tabs are real tabs and the example sheet is redacted and labelled", () => {
  const out = html(createElement(SignInScreen, { onCredential: () => {} }));
  expect(out).toContain('role="tablist"');
  expect(out.match(/role="tab"/g)).toHaveLength(3);
  expect(out.match(/aria-selected="true"/g)).toHaveLength(1);
  expect(out).toMatch(/role="tabpanel"[^>]*id="how-panel-redact"[^>]*aria-labelledby="how-tab-redact"/);
  // The first render shows the stored version: real bars, and no raw email or phone.
  expect(out).toContain('>email removed<');
  expect(out).toContain('>phone removed<');
  expect(out).not.toContain("analyst@example.com");
  expect(out).not.toContain("408-555-0190");
  expect(out).toContain("Example document");
  expect(out).toMatch(/aria-pressed="true"[^>]*>As stored</);
});

it("the phone layout puts the sign-in card first", () => {
  const out = html(createElement(SignInScreen, { onCredential: () => {} }));
  expect(out).toMatch(/<section class="order-first[^"]*lg:order-none/);
});

// --- client calls -------------------------------------------------------------------------

import { afterEach, vi } from "vitest";
import { adminActivity, deleteDocument } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

function capture(body: unknown) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}

it("deleteDocument encodes the engagement and a hostile name into the query", async () => {
  const calls = capture({ name: "x", chunks_deleted: 1 });
  await deleteDocument("acme", "a b&c=d?.txt");
  expect(calls[0].init.method).toBe("DELETE");
  expect(calls[0].url).toBe("http://localhost:8000/documents?engagement=acme&name=a%20b%26c%3Dd%3F.txt");
});

it("adminActivity sends limit, the paging cursor and the event filter", async () => {
  const calls = capture({ events: [], next_before: null });
  await adminActivity({ limit: 20, before: 41, event: "query" });
  expect(calls[0].url).toBe("http://localhost:8000/admin/activity?limit=20&before=41&event=query");
  await adminActivity();
  expect(calls[1].url).toBe("http://localhost:8000/admin/activity?limit=50");
});

it("access changes read plainly, by user or invitation number, with no emails", () => {
  expect(eventLabel("access")).toBe("Access change");
  expect(eventDetails(ev({ event: "access", action: "clearance_changed", target_user_id: "12", clearance: 2,
                           document: null, n_chunks: null, redaction_counts: null }))).toBe(
    "Clearance changed for user #12, clearance 2"
  );
  expect(eventDetails(ev({ event: "access", action: "invitation_revoked", invitation_id: 4, target_user_id: null,
                           clearance: null, document: null, n_chunks: null, redaction_counts: null }))).toBe(
    "Invitation revoked invitation #4"
  );
  const out = html(createElement(ActivityTable, { events: [ev({ event: "access", user_id: "system", action: "initial_admin_granted", target_user_id: "90", clearance: 3, document: null })] }));
  expect(out).toContain("System");
  expect(out).not.toMatch(/@/);
});
