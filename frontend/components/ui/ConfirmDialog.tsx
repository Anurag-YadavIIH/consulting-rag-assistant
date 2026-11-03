"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "./Button";

/**
 * A confirmation for destructive actions, on the native <dialog> element:
 * showModal() gives a real modal (focus moves inside, the page behind is
 * inert, Escape cancels). Focus starts on Cancel, the safe choice.
 */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal?.();
      cancelRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onCancel();
      }}
      className="w-[min(28rem,calc(100vw-2rem))] rounded-sm border border-rule bg-panel p-0 text-ink backdrop:bg-ink/50"
    >
      <div className="space-y-3 p-5">
        <h2 id="confirm-title" className="text-lg font-semibold text-ink">
          {title}
        </h2>
        {children ? <div className="text-sm text-muted">{children}</div> : null}
      </div>
      <div className="flex flex-wrap justify-end gap-2 border-t border-rule px-5 py-3">
        <button
          ref={cancelRef}
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="inline-flex min-h-target items-center rounded-sm border border-field bg-panel px-4 text-sm text-ink transition-colors hover:bg-raised disabled:cursor-not-allowed disabled:opacity-60"
        >
          Cancel
        </button>
        <Button
          onClick={onConfirm}
          disabled={busy}
          className="border-danger bg-danger text-panel hover:bg-danger/90"
        >
          {busy ? "Working..." : confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
