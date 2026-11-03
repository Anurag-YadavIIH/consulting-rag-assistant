import type { ReactNode } from "react";

type Tone = "neutral" | "accent" | "sidebar";

const TONES: Record<Tone, string> = {
  neutral: "border border-field bg-raised text-ink",
  accent: "border border-accent bg-accent text-on-accent",
  sidebar: "border border-side-border bg-side-raised text-side-text",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}
