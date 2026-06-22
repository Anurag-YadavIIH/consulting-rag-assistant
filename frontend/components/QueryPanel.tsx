"use client";

import { useState } from "react";
import { query, type QueryResponse } from "../lib/api";
import { ErrorBanner } from "./ErrorBanner";
import { SourceCard } from "./SourceCard";

export function QueryPanel({ engagement }: { engagement: string | undefined }) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await query(question, engagement);
      setResult(res);
    } catch (err) {
      setError(err);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit} className="space-y-2">
        <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide">
          Question
        </label>
        <textarea
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          rows={3}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about the engagement's documents..."
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="rounded-md bg-slate-800 text-white text-sm px-4 py-1.5 disabled:opacity-50"
        >
          {loading ? "Asking..." : "Ask"}
        </button>
      </form>

      {error ? <ErrorBanner error={error} /> : null}

      {!error && !loading && !result ? (
        <p className="text-sm text-slate-400">Ask a question to see an answer here.</p>
      ) : null}

      {result ? (
        <div className="space-y-3">
          <div className="rounded-md border border-slate-200 bg-white p-4 text-sm whitespace-pre-wrap">
            {result.answer}
          </div>

          <div>
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
              Sources
            </div>
            {result.citations.length === 0 ? (
              <p className="text-sm text-slate-400">No sources returned.</p>
            ) : (
              <div className="grid gap-2">
                {result.citations.map((c, i) => (
                  <SourceCard key={`${c.source_path}-${i}`} citation={c} />
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
