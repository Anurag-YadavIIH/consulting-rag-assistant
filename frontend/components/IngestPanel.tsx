"use client";

import { useState } from "react";
import { UPLOAD_ACCEPT, uploadDocument } from "../lib/api";
import { ErrorBanner } from "./ErrorBanner";

export function IngestPanel({ engagement }: { engagement: string | undefined }) {
  const [file, setFile] = useState<File | null>(null);
  const [clearance, setClearance] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<{ chunks: number; name: string } | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !engagement) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await uploadDocument(file, engagement, clearance);
      setResult({ chunks: res.chunks_ingested, name: res.source_name });
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
          Document
        </label>
        <input
          type="file"
          accept={UPLOAD_ACCEPT}
          className="w-full text-sm"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <p className="text-xs text-slate-400 mt-1">
          .txt, .md, .pdf or .pptx, up to 25 MB by default. The file is
          redacted on the server before anything is stored. Its filename is
          stored as-is and shown in citations, so keep sensitive details out
          of it. Uploading a name that already exists in this engagement
          replaces that document.
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
        <p className="text-xs text-slate-400 mt-1">
          The server enforces the caller&apos;s clearance ceiling regardless of
          what is entered here.
        </p>
      </div>

      <button
        type="submit"
        disabled={loading || !file || !engagement}
        className="rounded-md bg-slate-800 text-white text-sm px-4 py-1.5 disabled:opacity-50"
      >
        {loading ? "Uploading..." : "Upload"}
      </button>

      {error ? <ErrorBanner error={error} /> : null}
      {result !== null ? (
        <p className="text-sm text-emerald-700">
          Ingested {result.chunks} chunk{result.chunks === 1 ? "" : "s"} from{" "}
          <span className="font-mono">{result.name}</span>.
        </p>
      ) : null}
    </form>
  );
}
