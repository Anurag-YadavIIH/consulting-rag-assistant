/**
 * Colour tokens for both themes: the single source of truth. app/globals.css
 * defines the same values as CSS variables (RGB channels) and
 * __tests__/designTokens.test.ts checks the two match and that every text and
 * background pair meets WCAG contrast in both themes.
 *
 * The sidebar is dark in both themes. The accent always carries `onAccent`
 * (dark) text, never white.
 */

export type ThemeName = "light" | "dark";

export const TOKEN_NAMES = [
  "ground", // page background
  "panel", // cards and panels
  "raised", // hover and raised surfaces on panels
  "ink", // main text
  "muted", // secondary text
  "rule", // panel borders (decorative)
  "field", // form field borders (3:1 against panels)
  "link", // links
  "focus", // focus rings on the main surfaces
  "accent", // light blue
  "onAccent", // text on the accent
  "accentMuted", // disabled primary buttons: a muted accent tint
  "onAccentMuted", // text on accentMuted
  "highlight", // passage highlight
  "brandStrong", // "RAG" in the wordmark on main surfaces
  "redact", // redaction bars
  "redactEdge", // outline that keeps bars visible on dark panels
  "danger",
  "dangerBg",
  "ok",
  "okBg",
  "sideBg", // sidebar
  "sideRaised",
  "sideText",
  "sideMuted",
  "sideBorder",
] as const;

export type TokenName = (typeof TOKEN_NAMES)[number];

export const THEMES: Record<ThemeName, Record<TokenName, string>> = {
  light: {
    ground: "#EEF3F8",
    panel: "#FFFFFF",
    raised: "#F4F7F9",
    ink: "#15211E",
    muted: "#4D5C57",
    rule: "#C8D2CE",
    field: "#768782",
    link: "#1F5F99",
    focus: "#1F5F99",
    accent: "#7CC4FF",
    onAccent: "#15211E",
    accentMuted: "#CFE7FB",
    onAccentMuted: "#3D5568",
    highlight: "#FCE7A8",
    brandStrong: "#15211E",
    redact: "#15211E",
    redactEdge: "#15211E",
    danger: "#8A1C1C",
    dangerBg: "#FBEAEA",
    ok: "#1E5B34",
    okBg: "#E5F3EA",
    sideBg: "#15211E",
    sideRaised: "#243330",
    sideText: "#E6EDEA",
    sideMuted: "#A7B6B1",
    sideBorder: "#3A4A46",
  },
  dark: {
    ground: "#0F1716",
    panel: "#182321",
    raised: "#22302D",
    ink: "#EEF3F8",
    muted: "#B7C4BF",
    rule: "#3A4A46",
    field: "#6E817B",
    link: "#9AD2FF",
    focus: "#7CC4FF",
    accent: "#7CC4FF",
    onAccent: "#15211E",
    accentMuted: "#2A4256",
    onAccentMuted: "#C3D3E0",
    highlight: "#4A3F1E",
    brandStrong: "#7CC4FF",
    redact: "#000000",
    redactEdge: "#B7C4BF",
    danger: "#FFB4B4",
    dangerBg: "#3A1C1C",
    ok: "#A8E0BC",
    okBg: "#173323",
    sideBg: "#121D1B",
    sideRaised: "#22302D",
    sideText: "#EEF3F8",
    sideMuted: "#B7C4BF",
    sideBorder: "#3A4A46",
  },
};

/** "#15211E" -> "21 33 30", the CSS variable format Tailwind's
 * `rgb(var(--c-x) / <alpha-value>)` needs. */
export function toChannels(hex: string): string {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(" ");
}

export const cssVarName = (token: TokenName) =>
  `--c-${token.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`)}`;
