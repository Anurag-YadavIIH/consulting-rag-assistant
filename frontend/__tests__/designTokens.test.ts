/**
 * Design-system guarantees, in BOTH themes: WCAG contrast for every text and
 * background pair the UI uses, CSS variables matching lib/themeTokens.ts, no
 * white text (never on the accent), no raw HTML injection, no em dashes, no
 * gradients or large rounded corners in UI source.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { THEMES, TOKEN_NAMES, cssVarName, toChannels, type ThemeName, type TokenName } from "../lib/themeTokens";

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** `fg` at `alpha` over `bg`, as used by e.g. bg-highlight/50. */
function blend(fg: string, bg: string, alpha: number): string {
  const c = (h: string, i: number) => parseInt(h.slice(i, i + 2), 16);
  return (
    "#" +
    [1, 3, 5]
      .map((i) => Math.round(c(fg, i) * alpha + c(bg, i) * (1 - alpha)).toString(16).padStart(2, "0"))
      .join("")
  );
}

// [foreground, background] pairs, by token. Where the UI uses an opacity
// modifier (bg-highlight/50, bg-raised/60) the blended colour is checked too.
const TEXT_PAIRS: Array<[TokenName, TokenName]> = [
  ["ink", "ground"], ["ink", "panel"], ["ink", "raised"],
  ["muted", "ground"], ["muted", "panel"], ["muted", "raised"],
  ["link", "ground"], ["link", "panel"], ["link", "raised"],
  ["onAccent", "accent"],
  ["onAccentMuted", "accentMuted"], // disabled primary buttons
  ["ink", "highlight"],
  ["brandStrong", "panel"], ["brandStrong", "ground"],
  ["danger", "dangerBg"], ["danger", "panel"], ["danger", "raised"],
  ["ok", "okBg"],
  ["panel", "danger"], // destructive confirm button
  ["sideText", "sideBg"], ["sideText", "sideRaised"],
  ["sideMuted", "sideBg"], ["sideMuted", "sideRaised"],
  ["accent", "sideBg"], // "RAG" in the sidebar wordmark
];

const NON_TEXT_PAIRS: Array<[TokenName, TokenName]> = [
  ["field", "panel"], // form field boundaries
  ["focus", "panel"], ["focus", "ground"], ["focus", "raised"],
  ["accent", "sideBg"], ["accent", "sideRaised"], // focus rings on the sidebar
  ["sideBorder", "sideBg"], // theme control and quiet buttons need a visible edge
];

describe.each(["light", "dark"] as ThemeName[])("%s theme", (theme) => {
  const t = THEMES[theme];

  it.each(TEXT_PAIRS)("text %s on %s is at least 4.5:1", (fg, bg) => {
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5);
  });

  it.each(NON_TEXT_PAIRS)("non-text %s on %s is at least 3:1", (fg, bg) => {
    // sideBorder is decorative on the sidebar but should still be visible.
    const min = fg === "sideBorder" ? 1.4 : 3;
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(min);
  });

  it("blended surfaces keep text readable", () => {
    expect(contrast(t.ink, blend(t.highlight, t.panel, 0.5))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t.ink, blend(t.raised, t.panel, 0.6))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t.muted, blend(t.raised, t.panel, 0.6))).toBeGreaterThanOrEqual(4.5);
  });

  it("redaction bars stand out from panels and the passage highlight", () => {
    const edgeOrBar = Math.max(contrast(t.redact, t.panel), contrast(t.redactEdge, t.panel));
    expect(edgeOrBar).toBeGreaterThanOrEqual(3);
    const onHighlight = Math.max(
      contrast(t.redact, blend(t.highlight, t.panel, 0.5)),
      contrast(t.redactEdge, blend(t.highlight, t.panel, 0.5))
    );
    expect(onHighlight).toBeGreaterThanOrEqual(3);
  });

  it("the accent always carries dark text", () => {
    expect(t.onAccent).toBe("#15211E");
    expect(contrast("#FFFFFF", t.accent)).toBeLessThan(4.5); // why white is never used
  });
});

// --- the CSS variables match the tokens -------------------------------------------------

const CSS = readFileSync(resolve(__dirname, "../app/globals.css"), "utf8");

function block(selector: string): string {
  const start = CSS.indexOf(selector);
  expect(start, selector).toBeGreaterThanOrEqual(0);
  return CSS.slice(start, CSS.indexOf("}", start));
}

it.each([
  [":root {", "light"],
  [':root[data-theme="dark"] {', "dark"],
  [':root:not([data-theme="light"]) {', "dark"],
] as Array<[string, ThemeName]>)("CSS block %s has every %s token", (selector, theme) => {
  const css = block(selector);
  for (const token of TOKEN_NAMES) {
    expect(css, `${selector} ${token}`).toContain(`${cssVarName(token)}: ${toChannels(THEMES[theme][token])};`);
  }
});

// --- UI source rules ----------------------------------------------------------------------

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? sourceFiles(p) : /\.(tsx?|css)$/.test(name) ? [p] : [];
  });
}

const UI = ["app", "components"].flatMap((d) => sourceFiles(resolve(__dirname, "..", d)));

it("no white text, raw HTML injection or em dashes in UI source", () => {
  expect(UI.length).toBeGreaterThan(10);
  for (const file of UI) {
    const src = readFileSync(file, "utf8");
    expect(src, file).not.toMatch(/text-white|dangerouslySetInnerHTML|—/);
  }
});

it("no gradients, large rounded corners or all-caps labels", () => {
  for (const file of UI) {
    const src = readFileSync(file, "utf8");
    expect(src, file).not.toMatch(/bg-gradient|rounded-(md|lg|xl|2xl|3xl|full)\b|\buppercase\b/);
  }
});

it("the accent background is never paired with plain ink text (dark theme ink is light)", () => {
  for (const file of UI) {
    const src = readFileSync(file, "utf8");
    // Each class string (including each branch of a ternary) is double-quoted.
    for (const cls of src.match(/"[^"\n]*bg-accent[^"\n]*"/g) ?? []) {
      expect(cls, file).not.toMatch(/\btext-ink\b/);
    }
  }
});
