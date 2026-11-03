import type { Citation, Quote } from "../../lib/api";
import { RedactedText } from "../ui/RedactedText";

/**
 * An extractive answer: each quoted passage with its citation button and the
 * passage text only. No "Source: file [locator]" line and no empty brackets;
 * the source details live in the Sources panel. A quote whose number has no
 * citation is still shown, without a button.
 */
export function QuotedAnswer({
  quotes,
  citations,
  selected,
  onSelect,
}: {
  quotes: Quote[];
  citations: Citation[];
  selected: number | null;
  onSelect: (number: number) => void;
}) {
  const known = new Set(citations.map((c) => c.number));
  return (
    <ol className="space-y-4">
      {quotes.map((q, i) => (
        <li key={`${q.number}-${i}`} className="flex gap-3">
          {known.has(q.number) ? (
            <button
              type="button"
              onClick={() => onSelect(q.number)}
              aria-label={`Open source ${q.number}`}
              aria-pressed={selected === q.number}
              className={`inline-flex min-h-target min-w-target shrink-0 items-center justify-center rounded-sm border px-2 font-mono text-sm font-medium transition-colors ${
                selected === q.number
                  ? "border-accent bg-accent text-on-accent"
                  : "border-link bg-panel text-link hover:bg-raised"
              }`}
            >
              [{q.number}]
            </button>
          ) : null}
          <blockquote className="min-w-0 flex-1 whitespace-pre-wrap break-words text-lg leading-8 text-ink">
            <RedactedText text={q.text} />
          </blockquote>
        </li>
      ))}
    </ol>
  );
}
