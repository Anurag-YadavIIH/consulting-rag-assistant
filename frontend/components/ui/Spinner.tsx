/** A small busy indicator with a text label for screen readers. The spin
 * stops under prefers-reduced-motion (app/globals.css). */
export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-muted">
      <span aria-hidden="true" className="inline-block h-4 w-4 animate-spin border-2 border-field border-t-ink" />
      <span>{label}</span>
    </span>
  );
}
