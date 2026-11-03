import type { SelectHTMLAttributes } from "react";

export function Select({
  dark = false,
  className = "",
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { dark?: boolean }) {
  const tone = dark
    ? "border-side-border bg-side-raised text-side-text hover:border-side-muted"
    : "border-field bg-panel text-ink hover:border-ink/60";
  return (
    <select
      className={`block w-full min-h-target rounded-sm border px-2 text-base transition-colors ${tone} ${className}`}
      {...props}
    />
  );
}
