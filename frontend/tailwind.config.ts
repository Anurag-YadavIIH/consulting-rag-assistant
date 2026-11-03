import type { Config } from "tailwindcss";

/**
 * "Evidence desk" tokens. Every colour is a CSS variable (app/globals.css),
 * so each class works in both the light and dark theme. Values live in
 * lib/themeTokens.ts; contrast is checked in __tests__/designTokens.test.ts.
 */
const v = (name: string) => `rgb(var(--c-${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ground: v("ground"),
        panel: v("panel"),
        raised: v("raised"),
        ink: v("ink"),
        muted: v("muted"),
        rule: v("rule"),
        field: v("field"),
        link: v("link"),
        focus: v("focus"),
        accent: v("accent"),
        "on-accent": v("on-accent"),
        "accent-muted": v("accent-muted"),
        "on-accent-muted": v("on-accent-muted"),
        highlight: v("highlight"),
        "brand-strong": v("brand-strong"),
        redact: v("redact"),
        "redact-edge": v("redact-edge"),
        danger: v("danger"),
        "danger-bg": v("danger-bg"),
        ok: v("ok"),
        "ok-bg": v("ok-bg"),
        "side-bg": v("side-bg"),
        "side-raised": v("side-raised"),
        "side-text": v("side-text"),
        "side-muted": v("side-muted"),
        "side-border": v("side-border"),
      },
      fontFamily: {
        sans: ["var(--font-plex-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
        display: ["var(--font-sora)", "var(--font-plex-sans)", "system-ui", "sans-serif"],
      },
      fontSize: {
        // Small labels never go below 12px.
        xs: ["12px", { lineHeight: "16px" }],
        sm: ["14px", { lineHeight: "20px" }],
        base: ["16px", { lineHeight: "28px" }],
        lg: ["18px", { lineHeight: "30px" }],
        xl: ["20px", { lineHeight: "28px" }],
        title: ["32px", { lineHeight: "38px", letterSpacing: "-0.02em", fontWeight: "700" }],
      },
      borderRadius: {
        // Square or nearly square corners only.
        none: "0",
        sm: "2px",
        DEFAULT: "2px",
      },
      minHeight: { target: "44px" },
      minWidth: { target: "44px" },
      maxWidth: { page: "1400px" },
    },
  },
  plugins: [],
};

export default config;
