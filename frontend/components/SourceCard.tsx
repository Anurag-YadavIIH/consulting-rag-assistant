import type { Citation } from "../lib/api";

export function SourceCard({ citation }: { citation: Citation }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3 text-sm">
      <div className="font-mono text-xs text-slate-700 break-all">
        {citation.source_path}
      </div>
      {citation.locator ? (
        <div className="text-xs text-slate-500 mt-0.5">{citation.locator}</div>
      ) : null}
      <div className="mt-1 text-xs text-slate-400">
        score {citation.score.toFixed(3)}
      </div>
      {/* Future seam: a date/staleness badge belongs here, once the
          live-data layer (ARCHITECTURE.md §8) exists and /query actually
          returns one. Not built on the API side yet, so deliberately not
          rendered here either. */}
    </div>
  );
}
