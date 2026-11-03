"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { listDocuments, query, type QueryResponse } from "../../lib/api";
import { ANSWER_STYLE_NOTE } from "../../lib/config";
import { exampleQuestionsFor } from "../../lib/examples";
import { usedCitationNumbers } from "../../lib/citations";
import { ErrorBanner } from "../ErrorBanner";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { inputClass } from "../ui/Field";
import { Spinner } from "../ui/Spinner";
import { AnswerView } from "./AnswerView";
import { QuotedAnswer } from "./QuotedAnswer";
import { SourcePanel } from "./SourcePanel";

type DocCount = { engagement: string; count: number } | null;

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function AskWorkspace({ engagement }: { engagement: string | undefined }) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [docs, setDocs] = useState<DocCount>(null);
  const sourcesHeading = useRef<HTMLHeadingElement>(null);

  // Whether the engagement has any documents, so an empty one points to
  // Documents instead of inviting questions with nothing to answer from.
  useEffect(() => {
    setDocs(null);
    setResult(null);
    setSelected(null);
    setError(null);
    if (!engagement) return;
    let cancelled = false;
    listDocuments(engagement)
      .then((res) => {
        if (!cancelled) setDocs({ engagement, count: res.documents.length });
      })
      .catch(() => {
        // Not fatal: the question form still works; errors show on ask.
      });
    return () => {
      cancelled = true;
    };
  }, [engagement]);

  async function ask(q: string) {
    if (!q.trim() || loading) return;
    setLoading(true);
    setError(null);
    setCopied(false);
    try {
      const res = await query(q, engagement);
      setResult(res);
      setSelected(res.citations[0]?.number ?? null);
    } catch (err) {
      setError(err);
      setResult(null);
      setSelected(null);
    } finally {
      setLoading(false);
    }
  }

  function openSource(n: number) {
    setSelected(n);
    // Move focus to the source panel so keyboard and screen reader users
    // land on what they opened; on a phone this also scrolls it into view.
    requestAnimationFrame(() => {
      sourcesHeading.current?.focus();
      sourcesHeading.current?.scrollIntoView?.({
        block: "start",
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
    });
  }

  async function copyAnswer() {
    if (!result) return;
    // Copy what's shown: the quoted passages with their numbers in
    // extractive mode, the answer text otherwise.
    const quotes = result.quotes ?? [];
    const text =
      quotes.length > 0 ? quotes.map((q) => `[${q.number}] ${q.text}`).join("\n\n") : result.answer;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const examples = exampleQuestionsFor(engagement);
  const quotes = result?.quotes ?? [];
  const extractive = (result?.mode ?? "extractive") === "extractive";
  const used = result ? usedCitationNumbers(result.answer, result.citations, quotes) : [];
  const notFound = result !== null && result.citations.length === 0;
  const noDocuments = docs !== null && docs.engagement === engagement && docs.count === 0;
  const canAsk = !loading && question.trim().length > 0;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-title text-ink">Ask</h1>
        <p className="mt-2 max-w-prose text-base text-muted">
          Answers come from{" "}
          {engagement ? (
            <>
              the <span className="font-mono text-ink">{engagement}</span> engagement&apos;s documents
            </>
          ) : (
            "your engagement's documents"
          )}
          , and every passage is cited.
        </p>
      </header>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <div className="min-w-0 space-y-6">
          {noDocuments ? (
            <EmptyState
              title="This engagement has no documents yet"
              action={
                <Link
                  href="/documents/"
                  className="inline-flex min-h-target items-center rounded-sm border border-accent bg-accent px-4 text-sm font-medium text-on-accent transition-colors hover:bg-accent/85"
                >
                  Go to Documents to upload one
                </Link>
              }
            >
              Answers come only from uploaded documents.
            </EmptyState>
          ) : null}

          <form
            className="rounded-sm border border-rule bg-panel p-5"
            onSubmit={(e) => {
              e.preventDefault();
              void ask(question);
            }}
          >
            <label htmlFor="question" className="font-display text-xl font-semibold text-ink">
              Your question
            </label>
            <textarea
              id="question"
              rows={4}
              className={`${inputClass} mt-3 resize-y text-lg leading-7`}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="For example: what is the main barrier to adoption?"
            />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <div className="min-h-[24px]">{loading ? <Spinner label="Finding sources..." /> : null}</div>
              <Button type="submit" disabled={!canAsk} className="min-w-[8rem]">
                {loading ? "Asking..." : "Ask"}
              </Button>
            </div>
            {examples.length > 0 ? (
              <div className="mt-5 border-t border-rule pt-4">
                <p className="text-sm text-muted">Try an example</p>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {examples.map((ex) => (
                    <li key={ex}>
                      <Button
                        variant="chip"
                        disabled={loading}
                        onClick={() => {
                          setQuestion(ex);
                          void ask(ex);
                        }}
                      >
                        {ex}
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </form>

          {error ? <ErrorBanner error={error} /> : null}

          {!error && !loading && !result && !noDocuments ? (
            <EmptyState variant="calm" title="Results will appear here">
              You&apos;ll see the passages closest to your question, numbered so you can open
              each source on the right.
            </EmptyState>
          ) : null}

          {notFound && result ? (
            <section aria-labelledby="answer-heading" className="rounded-sm border border-rule bg-panel px-5 py-5">
              <h2 id="answer-heading" className="text-xl font-semibold text-ink">
                No answer found
              </h2>
              <p className="mt-2 text-base text-muted">{result.answer}</p>
            </section>
          ) : null}

          {result && !notFound ? (
            <section aria-labelledby="answer-heading" className="rounded-sm border border-rule bg-panel">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-5 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 id="answer-heading" className="text-xl font-semibold text-ink">
                    {extractive ? "Closest passages" : "Answer"}
                  </h2>
                  {extractive ? <Badge tone="neutral">Extractive</Badge> : null}
                </div>
                <Button variant="secondary" onClick={copyAnswer}>
                  {copied ? "Copied" : extractive ? "Copy passages" : "Copy answer"}
                </Button>
              </div>
              <div className="space-y-4 px-5 py-5">
                {extractive ? <p className="text-sm text-muted">{ANSWER_STYLE_NOTE}</p> : null}
                {quotes.length > 0 ? (
                  <QuotedAnswer
                    quotes={quotes}
                    citations={result.citations}
                    selected={selected}
                    onSelect={openSource}
                  />
                ) : (
                  <AnswerView
                    answer={result.answer}
                    citations={result.citations}
                    selected={selected}
                    onSelect={openSource}
                  />
                )}
              </div>
            </section>
          ) : null}
        </div>

        <div className="min-w-0 xl:sticky xl:top-10">
          <SourcePanel
            ref={sourcesHeading}
            citations={result?.citations ?? []}
            selected={selected}
            onSelect={openSource}
            used={used}
          />
        </div>
      </div>
    </div>
  );
}
