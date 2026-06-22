"use client";

import { useState } from "react";
import { ingest } from "../lib/api";
import { ErrorBanner } from "./ErrorBanner";

export function IngestPanel({ engagement }: { engagement: string | undefined }) {
  const [path, setPath] = useState("");
  const [clearance, setClearance] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [chunksIngested, setChunksIngested] = useState<number | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!path.trim() || !engagement) return;
    setLoading(true);
    setError(null);
    setChunksIngested(null);
    try {
      const res = await ingest(path, engagement, clearance);
      setChunksIngested(res.chunks_ingested);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div>
        <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
          Server-side path
        </label>
        <input
          type="text"
          className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm font-mono"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="data/sample/acme"
        />
        <p className="text-xs text-slate-400 mt-1">
          A path on the server's filesystem — not a file upload. The server
          enforces the caller&apos;s clearance ceiling regardless of what is
          entered below.
        </p>
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
          Engagement
        </label>
        <input
          type="text"
          disabled
          className="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-500"
          value={engagement ?? "(select an engagement above)"}
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
          Clearance
        </label>
        <input
          type="number"
          min={1}
          className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          value={clearance}
          onChange={(e) => setClearance(Number(e.target.value))}
        />
      </div>

      <button
        type="submit"
        disabled={loading || !path.trim() || !engagement}
        className="rounded-md bg-slate-800 text-white text-sm px-4 py-1.5 disabled:opacity-50"
      >
        {loading ? "Ingesting..." : "Ingest"}
      </button>

      {error ? <ErrorBanner error={error} /> : null}
      {chunksIngested !== null ? (
        <p className="text-sm text-emerald-700">
          Ingested {chunksIngested} chunk{chunksIngested === 1 ? "" : "s"}.
        </p>
      ) : null}
    </form>
  );
}
