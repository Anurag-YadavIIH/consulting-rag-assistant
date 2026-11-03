import type { Citation } from "../../lib/api";
import { parseCitationMarkers } from "../../lib/citations";
import { RedactedText } from "../ui/RedactedText";

/**
 * The answer as plain text, with each [n] that matches a citation turned into
 * a button that opens that source. Markers with no matching citation stay as
 * text; an answer with no markers is just text.
 */
export function AnswerView({
  answer,
  citations,
  selected,
  onSelect,
}: {
  answer: string;
  citations: Citation[];
  selected: number | null;
  onSelect: (number: number) => void;
}) {
  const segments = parseCitationMarkers(answer, citations.map((c) => c.number));
  return (
    <div className="whitespace-pre-wrap break-words text-lg leading-8 text-ink">
      {segments.map((seg, i) =>
        seg.kind === "text" ? (
          <RedactedText key={i} text={seg.text} />
        ) : (
          <button
            key={i}
            type="button"
            onClick={() => onSelect(seg.number)}
            aria-label={`Open source ${seg.number}`}
            aria-pressed={selected === seg.number}
            // 28px, not 44: an inline target in running text (WCAG 2.5.8
            // inline exception); every source also has a 44px button in
            // the source list.
            className={`mx-0.5 inline-flex min-h-[28px] min-w-[32px] items-center justify-center rounded-sm border px-1 align-middle font-mono text-sm font-medium transition-colors ${
              selected === seg.number ? "border-accent bg-accent text-on-accent" : "border-link bg-panel text-link hover:bg-raised"
            }`}
          >
            {seg.text}
          </button>
        )
      )}
    </div>
  );
}
