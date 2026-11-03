import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "quiet" | "chip" | "sidebar";

const VARIANTS: Record<Variant, string> = {
  // The accent always carries on-accent (dark) text, never white.
  primary: "border border-accent bg-accent font-medium text-on-accent hover:bg-accent/85",
  secondary: "border border-field bg-panel text-ink hover:bg-raised",
  quiet: "border border-transparent bg-transparent text-link hover:underline",
  // Light example-question chips: still a 44px target, visually quiet.
  chip: "border border-rule bg-transparent px-3 text-left text-sm text-link hover:border-field hover:bg-raised",
  // Quiet button for the always-dark sidebar.
  sidebar: "border border-side-border bg-transparent text-side-text hover:bg-side-raised",
};

// A clear disabled look, not just lower opacity. The primary action keeps a
// muted accent tint so it still reads as the main button; others go neutral.
const DISABLED =
  "disabled:cursor-not-allowed disabled:border-rule disabled:bg-raised disabled:text-muted disabled:hover:bg-raised";
const DISABLED_PRIMARY =
  "disabled:cursor-not-allowed disabled:border-accent-muted disabled:bg-accent-muted disabled:font-medium disabled:text-on-accent-muted disabled:hover:bg-accent-muted";

export function Button({
  variant = "primary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={`inline-flex min-h-target items-center justify-center gap-2 rounded-sm px-4 text-sm transition-colors ${VARIANTS[variant]} ${variant === "sidebar" ? "" : variant === "primary" ? DISABLED_PRIMARY : DISABLED} ${className}`}
      {...props}
    />
  );
}
