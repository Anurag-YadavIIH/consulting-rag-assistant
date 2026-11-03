import { forwardRef } from "react";
import type { Citation } from "../../lib/api";
import { SourceCard } from "../SourceCard";
import { EmptyState } from "../ui/EmptyState";

function SourceButton({
  citation: c,
  active,
  used,
  onSelect,
}: {
  citation: Citation;
  active: boolean;
  used: boolean;
  onSelect: (number: number) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(c.number)}
      aria-pressed={active}
      className={`flex min-h-target w-full items-start gap-2 rounded-sm border px-3 py-2 text-left text-sm transition-colors ${
        active ? "border-accent bg-accent text-on-accent" : "border-rule bg-panel text-ink hover:bg-raised"
      }`}
    >
      <span className="font-mono text-xs font-medium">[{c.number}]</span>
      <span className="min-w-0 flex-1">
        <span className="block break-all font-mono text-xs">{c.source_path}</span>
        {c.locator ? (
          <span className={`block text-xs ${active ? "text-on-accent" : "text-muted"}`}>{c.locator}</span>
        ) : null}
      </span>
      {used ? <span className="sr-only">(used in the answer)</span> : null}
    </button>
  );
}

/**
 * Every source the answer drew on, plus the selected one in full. Sources the
 * answer actually uses (`used`, in order of use) come first; the rest are
 * listed under "Other retrieved passages". Numbers always match the answer.
 * Works on its own: nothing depends on the answer containing [n] markers.
 * The heading takes focus (tabIndex -1) when a source is opened.
 */
export const SourcePanel = forwardRef<
  HTMLHeadingElement,
  {
    citations: Citation[];
    selected: number | null;
    onSelect: (number: number) => void;
    used?: number[];
  }
>(function SourcePanel({ citations, selected, onSelect, used = [] }, headingRef) {
  const current = citations.find((c) => c.number === selected) ?? null;
  const byNumber = new Map(citations.map((c) => [c.number, c]));
  const usedList = used.map((n) => byNumber.get(n)).filter((c): c is Citation => c !== undefined);
  const usedSet = new Set(usedList.map((c) => c.number));
  const others = citations.filter((c) => !usedSet.has(c.number));

  return (
    <section aria-labelledby="sources-heading" className="rounded-sm border border-rule bg-panel">
      <div className="border-b border-rule px-5 py-3">
        <h2 id="sources-heading" ref={headingRef} tabIndex={-1} className="text-xl font-semibold text-ink">
          Sources{citations.length ? ` (${citations.length})` : ""}
        </h2>
      </div>
      <div className="space-y-4 p-5">
        {citations.length === 0 ? (
          <EmptyState variant="calm" title="No sources yet">
            Sources appear here after you ask a question.
          </EmptyState>
        ) : (
          <>
            {usedList.length > 0 ? (
              <div>
                <h3 className="mb-2 text-sm font-semibold text-ink">Used in the answer</h3>
                <ul className="space-y-1" aria-label="Sources used in the answer">
                  {usedList.map((c) => (
                    <li key={c.number}>
                      <SourceButton citation={c} active={c.number === selected} used onSelect={onSelect} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {others.length > 0 ? (
              <div>
                <h3 className="mb-2 text-sm font-semibold text-muted">
                  {usedList.length > 0 ? "Other retrieved passages" : "Retrieved passages"}
                </h3>
                <ul className="space-y-1" aria-label="Other retrieved passages">
                  {others.map((c) => (
                    <li key={c.number}>
                      <SourceButton citation={c} active={c.number === selected} used={false} onSelect={onSelect} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {current ? (
              <div className="border-t border-rule pt-4">
                <SourceCard citation={current} />
              </div>
            ) : (
              <p className="text-sm text-muted">Select a source to read its passage.</p>
            )}
          </>
        )}
      </div>
    </section>
  );
});
