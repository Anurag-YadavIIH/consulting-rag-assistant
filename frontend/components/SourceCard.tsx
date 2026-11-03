import type { Citation } from "../lib/api";
import { RedactedText } from "./ui/RedactedText";

/**
 * One source in full: filename, locator, relevance and the passage text.
 * Every field is untrusted text rendered as React text; redaction bars appear
 * only for real markers in the passage. Clearance isn't shown because
 * citations don't carry it.
 */
export function SourceCard({ citation }: { citation: Citation }) {
  return (
    <article className="space-y-3 text-sm">
      <div>
        <div className="text-xs text-muted">Source [{citation.number}]</div>
        <div className="mt-1 break-all font-mono text-sm text-ink">{citation.source_path}</div>
        <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {citation.locator ? (
            <div className="flex gap-1">
              <dt>Location</dt>
              <dd className="font-mono text-ink">{citation.locator}</dd>
            </div>
          ) : null}
          {/* Scores aren't confidences. Only a similarity score is shown as
              a number; keyword matches use a different, unbounded scale. */}
          {citation.score_kind === "similarity" ? (
            <div className="flex gap-1">
              <dt>Similarity</dt>
              <dd className="font-mono text-ink">{citation.score.toFixed(3)}</dd>
            </div>
          ) : citation.score_kind === "keyword" ? (
            <div className="flex gap-1">
              <dt>Found by</dt>
              <dd className="text-ink">keyword match</dd>
            </div>
          ) : null}
        </dl>
      </div>
      <blockquote className="whitespace-pre-wrap break-words border border-rule bg-highlight/50 px-4 py-3 text-base leading-7 text-ink">
        <RedactedText text={citation.text} />
      </blockquote>
    </article>
  );
}
