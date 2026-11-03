import type { ReactNode } from "react";

/** A labelled form control. `children` is the control; give it `id={id}`. */
export function Field({
  id,
  label,
  hint,
  children,
  dark = false,
}: {
  id: string;
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  dark?: boolean;
}) {
  return (
    <div>
      <label htmlFor={id} className={`mb-1.5 block text-sm font-medium ${dark ? "text-side-muted" : "text-ink"}`}>
        {label}
      </label>
      {children}
      {hint ? (
        <p id={`${id}-hint`} className={`mt-1.5 text-sm ${dark ? "text-side-muted" : "text-muted"}`}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}

// 16px text in fields also stops phones zooming in on focus.
export const inputClass =
  "block w-full min-h-target rounded-sm border border-field bg-panel px-3 py-2 text-base text-ink placeholder:text-muted transition-colors hover:border-ink/60";
