/**
 * Ask workspace pieces rendered to static HTML: redaction bars only for real
 * markers, citation buttons, source panel selection, and untrusted text
 * staying escaped.
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import type { Citation } from "../lib/api";
import { splitRedactions } from "../lib/redaction";
import { exampleQuestionsFor } from "../lib/examples";
import { RedactedText } from "../components/ui/RedactedText";
import { AnswerView } from "../components/ask/AnswerView";
import { SourcePanel } from "../components/ask/SourcePanel";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: unknown }) =>
    createElement("a", { href }, children as never),
}));

const html = (el: ReturnType<typeof createElement>) => renderToStaticMarkup(el);

function cite(number: number, over: Partial<Citation> = {}): Citation {
  return {
    number,
    source_path: `doc${number}.txt`,
    locator: number === 1 ? "slide 1" : "",
    score: 0.5 + number / 100,
    text: `Passage ${number} text.`,
    score_kind: "similarity",
    ...over,
  };
}

// --- redaction bars ---------------------------------------------------------------

it("draws a bar with an accessible label for each known redaction marker", () => {
  const out = html(createElement(RedactedText, { text: "Call [REDACTED_EMAIL] or [REDACTED_PHONE]." }));
  expect(out.match(/data-redacted=/g)).toHaveLength(2);
  expect(out).toContain('aria-label="Redacted email address"');
  expect(out).toContain('aria-label="Redacted phone number"');
  expect(out).toContain('role="img"');
  expect(out).not.toContain("[REDACTED_EMAIL]");
});

it("leaves unknown labels and look-alikes as plain text, never a bar", () => {
  for (const text of ["[REDACTED_SECRET]", "[REDACTED_email]", "[REDACTED]", "[REDACTED_ EMAIL]", "REDACTED_EMAIL"]) {
    const out = html(createElement(RedactedText, { text }));
    expect(out).not.toContain("data-redacted");
    expect(splitRedactions(text)).toEqual([{ kind: "text", text }]);
  }
});

it("draws no bars for text without markers", () => {
  expect(html(createElement(RedactedText, { text: "Plain passage." }))).not.toContain("data-redacted");
});

it("covers every label the server's redactor can emit", () => {
  for (const label of ["EMAIL", "SSN", "CREDIT_CARD", "PHONE", "MRN", "NPI", "IP_ADDRESS", "CUSTOM"]) {
    expect(splitRedactions(`[REDACTED_${label}]`)[0].kind).toBe("redacted");
  }
});

// --- the answer ---------------------------------------------------------------------

it("turns matching markers into buttons and keeps the rest as text", () => {
  const out = html(
    createElement(AnswerView, {
      answer: "First [1], missing [7], second [2].",
      citations: [cite(1), cite(2)],
      selected: 2,
      onSelect: () => {},
    })
  );
  expect(out.match(/<button/g)).toHaveLength(2);
  expect(out).toContain('aria-label="Open source 1"');
  expect(out).toContain("missing [7]");
  expect(out).toMatch(/aria-pressed="true"[^>]*>\[2\]/);
});

it("an answer with no markers renders without buttons", () => {
  const out = html(createElement(AnswerView, { answer: "Just text.", citations: [cite(1)], selected: null, onSelect: () => {} }));
  expect(out).not.toContain("<button");
  expect(out).toContain("Just text.");
});

it("escapes a hostile answer", () => {
  const out = html(
    createElement(AnswerView, {
      answer: '<img src=x onerror="alert(1)"> [1]',
      citations: [cite(1)],
      selected: null,
      onSelect: () => {},
    })
  );
  expect(out).not.toContain("<img");
  expect(out).toContain("&lt;img");
});

// --- the source panel -----------------------------------------------------------------

it("lists every source and shows the selected one in full", () => {
  const out = html(
    createElement(SourcePanel, {
      citations: [cite(1), cite(2, { text: "Contact [REDACTED_EMAIL] for terms." })],
      selected: 2,
      onSelect: () => {},
    })
  );
  expect(out).toContain("Sources (2)");
  expect(out.match(/aria-pressed="true"/g)).toHaveLength(1);
  expect(out).toContain("doc1.txt");
  expect(out).toContain("Contact ");
  expect(out).toContain('aria-label="Redacted email address"'); // passage of source 2
  expect(out).not.toContain("Passage 1 text."); // source 1 isn't open
  expect(out).toContain("Similarity");
  expect(out).not.toContain("Clearance"); // citations don't carry it
});

it("works with nothing selected and with no sources", () => {
  const some = html(createElement(SourcePanel, { citations: [cite(1)], selected: null, onSelect: () => {} }));
  expect(some).toContain("Select a source to read its passage.");
  const none = html(createElement(SourcePanel, { citations: [], selected: null, onSelect: () => {} }));
  expect(none).toContain("No sources yet");
});

it("a selection that matches no source doesn't crash", () => {
  const out = html(createElement(SourcePanel, { citations: [cite(1)], selected: 9, onSelect: () => {} }));
  expect(out).toContain("Select a source to read its passage.");
});

it("escapes hostile filenames, locators and passages in the panel", () => {
  const hostile = cite(1, {
    source_path: '<img src=x onerror="alert(1)">.pdf',
    locator: "<b>page</b>",
    text: "<script>alert(1)</script>",
  });
  const out = html(createElement(SourcePanel, { citations: [hostile], selected: 1, onSelect: () => {} }));
  expect(out).not.toContain("<img");
  expect(out).not.toContain("<script>");
  expect(out).not.toContain("<b>");
  expect(out).toContain("&lt;script&gt;");
});

// --- examples -------------------------------------------------------------------------

it("example questions only for the engagements they were written for", () => {
  expect(exampleQuestionsFor("acme").length).toBeGreaterThan(0);
  expect(exampleQuestionsFor("meridian").length).toBeGreaterThan(0);
  expect(exampleQuestionsFor("kestrel").length).toBeGreaterThan(0);
  expect(exampleQuestionsFor("globex")).toEqual([]);
  expect(exampleQuestionsFor("toString")).toEqual([]); // no prototype keys
  expect(exampleQuestionsFor(undefined)).toEqual([]);
});

// --- quoted (extractive) answers ------------------------------------------------------

import { QuotedAnswer } from "../components/ask/QuotedAnswer";
import { usedCitationNumbers } from "../lib/citations";

it("shows each quoted passage with its citation button and no source line or empty brackets", () => {
  const out = html(
    createElement(QuotedAnswer, {
      quotes: [{ number: 1, text: "TAM estimated at 2.4B by 2030" }],
      citations: [cite(1, { source_path: "deck.pptx", locator: "" })],
      selected: 1,
      onSelect: () => {},
    })
  );
  expect(out).toContain('aria-label="Open source 1"');
  expect(out).toContain("TAM estimated at 2.4B by 2030");
  expect(out).not.toContain("Source:");
  expect(out).not.toContain("[]");
  expect(out).not.toContain("Based on the retrieved material");
  expect(out).not.toContain("Offline extractive mode");
});

it("a quote whose number has no citation is shown without a button", () => {
  const out = html(
    createElement(QuotedAnswer, { quotes: [{ number: 4, text: "orphan" }], citations: [cite(1)], selected: null, onSelect: () => {} })
  );
  expect(out).toContain("orphan");
  expect(out).not.toContain("<button");
});

it("quoted passages draw real redaction bars and stay escaped", () => {
  const out = html(
    createElement(QuotedAnswer, {
      quotes: [{ number: 1, text: "Contact [REDACTED_EMAIL] <script>x</script>" }],
      citations: [cite(1)],
      selected: null,
      onSelect: () => {},
    })
  );
  expect(out).toContain('aria-label="Redacted email address"');
  expect(out).not.toContain("<script>");
});

it("used citations: the quotes in extractive mode, the matching markers otherwise", () => {
  const cits = [cite(1), cite(2), cite(3)];
  expect(usedCitationNumbers("ignored [3]", cits, [{ number: 2, text: "q" }])).toEqual([2]);
  expect(usedCitationNumbers("A [3] then [1] and [3] again, [9]", cits)).toEqual([3, 1]);
  expect(usedCitationNumbers("no markers", cits)).toEqual([]);
  expect(usedCitationNumbers("x", cits, [{ number: 7, text: "unknown" }])).toEqual([]);
});

it("the source panel lists used sources first, then other retrieved passages, keeping numbers", () => {
  const out = html(
    createElement(SourcePanel, { citations: [cite(1), cite(2), cite(3)], selected: 1, onSelect: () => {}, used: [3] })
  );
  const usedAt = out.indexOf("Used in the answer");
  const otherAt = out.indexOf("Other retrieved passages");
  expect(usedAt).toBeGreaterThan(-1);
  expect(otherAt).toBeGreaterThan(usedAt);
  expect(out.indexOf("doc3.txt")).toBeLessThan(otherAt); // [3] is in the used group
  expect(out.indexOf("doc1.txt")).toBeGreaterThan(otherAt);
  expect(out).toContain("[3]");
  expect(out).toContain("(used in the answer)");
});

it("with nothing marked as used, the list is just the retrieved passages", () => {
  const out = html(createElement(SourcePanel, { citations: [cite(1)], selected: null, onSelect: () => {} }));
  expect(out).not.toContain("Used in the answer");
  expect(out).toContain("Retrieved passages");
});

it("acme examples are answerable from clearance 1 sample content", () => {
  expect(exampleQuestionsFor("acme")).not.toContain("What is the main barrier to adoption?");
});

it("only similarity scores are shown as numbers; keyword matches never are", async () => {
  const { SourceCard } = await import("../components/SourceCard");
  const sim = html(createElement(SourceCard, { citation: cite(1, { score: 0.826 }) }));
  expect(sim).toContain("Similarity");
  expect(sim).toContain("0.826");
  const kw = html(createElement(SourceCard, { citation: cite(2, { score: 7.25, score_kind: "keyword" }) }));
  expect(kw).toContain("keyword match");
  expect(kw).not.toContain("7.250");
  expect(kw).not.toContain("Similarity");
  const other = html(createElement(SourceCard, { citation: cite(3, { score: 3.5, score_kind: "other" }) }));
  expect(other).not.toContain("3.500");
  expect(sim + kw + other).not.toMatch(/%|confidence/i);
});
