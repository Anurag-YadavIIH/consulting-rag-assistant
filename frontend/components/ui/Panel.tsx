import type { HTMLAttributes, ReactNode } from "react";

export function Panel({
  title,
  actions,
  children,
  className = "",
  ...props
}: HTMLAttributes<HTMLElement> & { title?: ReactNode; actions?: ReactNode }) {
  return (
    <section className={`rounded-sm border border-rule bg-panel ${className}`} {...props}>
      {title || actions ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-5 py-3">
          {title ? <h2 className="text-lg font-semibold text-ink">{title}</h2> : <span />}
          {actions}
        </div>
      ) : null}
      <div className="p-5">{children}</div>
    </section>
  );
}
