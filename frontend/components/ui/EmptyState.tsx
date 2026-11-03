import type { ReactNode } from "react";

/**
 * "calm": plain text in the flow of the page, for "nothing here yet".
 * "boxed": a bordered panel, for a state that needs action (like an
 * engagement with no documents).
 */
export function EmptyState({
  title,
  children,
  action,
  variant = "boxed",
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  variant?: "calm" | "boxed";
}) {
  const frame = variant === "boxed" ? "rounded-sm border border-field bg-panel px-5 py-5" : "py-2";
  return (
    <div className={`text-sm ${frame}`}>
      <p className="font-display text-base font-semibold text-ink">{title}</p>
      {children ? <div className="mt-1 max-w-prose text-muted">{children}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
