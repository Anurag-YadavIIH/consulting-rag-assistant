"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { RedactedText } from "../ui/RedactedText";

// What the product does, limited to what the code enforces:
//  - redaction runs in the ingestion pipeline before chunking, embedding and storage
//  - retrieval is filtered by engagement membership and clearance (SQL + AccessPolicy)
//  - every displayed passage carries a citation to its source document
// The sample sheets are made up (example.com, a 555 number) and labelled as examples.
export const POINTS: Array<{ id: string; title: string; body: string }> = [
  {
    id: "redact",
    title: "Redacted first",
    body: "Emails, phone numbers and other identifiers are removed on the server before a document is stored or searched.",
  },
  {
    id: "engagement",
    title: "Separated by engagement",
    body: "You only see documents from the engagements you belong to, at your clearance level.",
  },
  {
    id: "cited",
    title: "Every passage cited",
    body: "Results are passages quoted from your documents, each linked to its source file and location.",
  },
];

const ADVANCE_MS = 6500;
const UPLOADED = "Lead analyst contact: analyst@example.com, direct line +1 408-555-0190. Pilot sites cite staff training as the main barrier to adoption.";
const STORED = "Lead analyst contact: [REDACTED_EMAIL], direct line [REDACTED_PHONE]. Pilot sites cite staff training as the main barrier to adoption.";

const DOCS: Array<{ engagement: string; name: string; clearance: number; reason: string | null }> = [
  { engagement: "acme", name: "pilot_review.txt", clearance: 1, reason: null },
  { engagement: "acme", name: "board_minutes.txt", clearance: 3, reason: "Above your clearance" },
  { engagement: "globex", name: "market_scan.txt", clearance: 1, reason: "Not your engagement" },
];

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

/** The three product points as tabs, each with a small example sheet. */
export function HowItWorks() {
  const [active, setActive] = useState(0);
  const [stored, setStored] = useState(true);
  const [autoplay, setAutoplay] = useState(false);
  const [paused, setPaused] = useState(false);
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);

  // Autoplay only after mount, and never when the user prefers less motion.
  useEffect(() => setAutoplay(!prefersReducedMotion()), []);

  useEffect(() => {
    if (!autoplay || paused) return;
    const t = window.setTimeout(() => setActive((a) => (a + 1) % POINTS.length), ADVANCE_MS);
    return () => window.clearTimeout(t);
  }, [autoplay, paused, active]);

  // On the redaction sheet, play "uploaded" then "stored" so the bars sweep in.
  useEffect(() => {
    if (!autoplay || active !== 0) return;
    setStored(false);
    const t = window.setTimeout(() => setStored(true), 1600);
    return () => window.clearTimeout(t);
  }, [autoplay, active]);

  const choose = (i: number) => {
    setAutoplay(false); // the user is in control from here on
    setActive(i);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const next = { ArrowDown: i + 1, ArrowRight: i + 1, ArrowUp: i - 1, ArrowLeft: i - 1, Home: 0, End: POINTS.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const j = (next + POINTS.length) % POINTS.length;
    choose(j);
    tabs.current[j]?.focus();
  };

  const point = POINTS[active];
  return (
    <div
      className="mt-8 grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] xl:items-start"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <div role="tablist" aria-label="How ConsultRAG protects your documents" aria-orientation="vertical" className="space-y-2">
        {POINTS.map((p, i) => {
          const selected = i === active;
          return (
            <button
              key={p.id}
              ref={(el) => {
                tabs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`how-tab-${p.id}`}
              aria-selected={selected}
              aria-controls={`how-panel-${p.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => choose(i)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={`relative flex w-full min-h-target gap-3 overflow-hidden border px-4 py-3 text-left transition-colors ${
                selected
                  ? "border-side-border bg-side-raised"
                  : "border-transparent hover:border-side-border hover:bg-side-raised/50"
              }`}
            >
              <span
                aria-hidden="true"
                className={`mt-1 font-mono text-xs ${selected ? "text-accent" : "text-side-muted"}`}
              >
                0{i + 1}
              </span>
              <span className="min-w-0">
                <span className="block font-display text-lg font-semibold text-side-text">{p.title}</span>
                <span className={`block text-sm text-side-muted ${selected ? "" : "sr-only"}`}>{p.body}</span>
              </span>
              <span
                aria-hidden="true"
                className={`absolute inset-y-0 left-0 w-1 ${selected ? "bg-accent" : "bg-transparent"}`}
              />
              {selected && autoplay && !paused ? (
                <span
                  key={`progress-${active}`}
                  aria-hidden="true"
                  className="animate-tab-progress absolute bottom-0 left-0 h-0.5 w-full origin-left bg-accent"
                />
              ) : null}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`how-panel-${point.id}`}
        aria-labelledby={`how-tab-${point.id}`}
        className="border border-side-border bg-panel text-ink shadow-[0_18px_40px_-20px_rgba(0,0,0,0.6)]"
      >
        <div key={point.id} className="animate-sheet-in">
          {point.id === "redact" ? (
            <RedactSheet stored={stored} onToggle={(v) => { setAutoplay(false); setStored(v); }} />
          ) : point.id === "engagement" ? (
            <EngagementSheet />
          ) : (
            <CitedSheet />
          )}
        </div>
      </div>
    </div>
  );
}

function SheetHeader({ name, note }: { name: string; note: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-rule bg-raised px-4 py-2">
      <span className="truncate font-mono text-xs text-ink">{name}</span>
      <span className="shrink-0 text-xs text-muted">{note}</span>
    </div>
  );
}

function RedactSheet({ stored, onToggle }: { stored: boolean; onToggle: (stored: boolean) => void }) {
  return (
    <>
      <SheetHeader name="acme_research.txt" note="Example document" />
      <div className="space-y-4 px-4 py-4">
        <div className="inline-flex border border-rule" role="group" aria-label="Which version to show">
          {[
            { label: "As uploaded", value: false },
            { label: "As stored", value: true },
          ].map((o) => (
            <button
              key={o.label}
              type="button"
              aria-pressed={stored === o.value}
              onClick={() => onToggle(o.value)}
              className={`min-h-target px-3 text-sm font-medium transition-colors ${
                stored === o.value ? "bg-ink text-panel" : "bg-panel text-muted hover:text-ink"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
        <p key={stored ? "stored" : "uploaded"} className={`text-base leading-7 ${stored ? "demo-sweep" : ""}`}>
          {stored ? <RedactedText text={STORED} /> : UPLOADED}
        </p>
        <p className="text-xs text-muted">
          {stored
            ? "Only this version is embedded, indexed and shown in answers."
            : "This is what was uploaded. It never reaches storage."}
        </p>
      </div>
    </>
  );
}

function EngagementSheet() {
  return (
    <>
      <SheetHeader name="Signed in: Analyst in acme, clearance 1" note="Example" />
      <ul className="divide-y divide-rule">
        {DOCS.map((d) => (
          <li key={d.name} className="flex items-center justify-between gap-3 px-4 py-3">
            <span className={`min-w-0 ${d.reason ? "opacity-60" : ""}`}>
              <span className="block truncate font-mono text-sm text-ink">{d.name}</span>
              <span className="block text-xs text-muted">
                {d.engagement}, clearance {d.clearance}
              </span>
            </span>
            {d.reason ? (
              <span className="shrink-0 border border-rule px-2 py-0.5 text-xs text-muted">{d.reason}</span>
            ) : (
              <span className="shrink-0 bg-ok-bg px-2 py-0.5 text-xs font-medium text-ok">Searchable</span>
            )}
          </li>
        ))}
      </ul>
      <p className="border-t border-rule px-4 py-3 text-xs text-muted">
        Hidden documents are filtered out in the database query, not just in the page.
      </p>
    </>
  );
}

function CitedSheet() {
  return (
    <>
      <SheetHeader name="What is the main barrier to adoption?" note="Example answer" />
      <div className="space-y-3 px-4 py-4">
        <blockquote className="border border-rule bg-highlight/50 px-4 py-3 text-base leading-7 text-ink">
          Pilot sites cite staff training as the main barrier to adoption.
          <span className="ml-1 align-super text-xs font-semibold text-link">[1]</span>
        </blockquote>
        <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted">
          <span className="font-semibold text-ink">[1]</span>
          <span className="font-mono text-ink">acme_research.txt</span>
          <span>chunk 2</span>
        </div>
        <p className="text-xs text-muted">Each passage shown links back to the file and place it came from.</p>
      </div>
    </>
  );
}
