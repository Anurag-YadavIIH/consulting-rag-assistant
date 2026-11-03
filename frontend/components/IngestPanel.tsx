"use client";

import { useRef, useState } from "react";
import { UPLOAD_ACCEPT, uploadDocument } from "../lib/api";
import { MAX_CLEARANCE, MIN_CLEARANCE } from "../lib/team";
import { checkUploadFile, pickDroppedFile } from "../lib/uploads";
import { ErrorBanner } from "./ErrorBanner";
import { Button } from "./ui/Button";
import { Field, inputClass } from "./ui/Field";
import { Spinner } from "./ui/Spinner";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function IngestPanel({
  engagement,
  onUploaded,
}: {
  engagement: string | undefined;
  onUploaded?: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [clearance, setClearance] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<{ chunks: number; name: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function accept(candidate: File | null, problem: string | null) {
    setResult(null);
    setError(null);
    setFileError(problem);
    setFile(candidate);
  }

  function onPicked(f: File | undefined) {
    if (!f) return accept(null, null);
    const problem = checkUploadFile(f);
    if (problem && inputRef.current) inputRef.current.value = "";
    accept(problem ? null : f, problem);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !engagement) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await uploadDocument(file, engagement, clearance);
      setResult({ chunks: res.chunks_ingested, name: res.source_name });
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      onUploaded?.();
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <p className="text-base text-muted">
        Uploading to{" "}
        {engagement ? (
          <span className="font-mono font-medium text-ink">{engagement}</span>
        ) : (
          <span className="text-ink">no engagement (choose one in the sidebar)</span>
        )}
      </p>

      <div>
        {/* The native input stays in the page (visually hidden, still
            focusable and labelled); the zone is its label and a drop target
            that applies the same checks. */}
        <label
          htmlFor="upload-file"
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const { file: dropped, error: problem } = pickDroppedFile(e.dataTransfer.files);
            if (dropped || problem) accept(dropped, problem);
          }}
          className={`flex min-h-[10rem] cursor-pointer flex-col items-center justify-center gap-2 rounded-sm border-2 px-6 py-8 text-center transition-colors focus-within:outline focus-within:outline-[3px] focus-within:outline-offset-2 focus-within:outline-focus ${
            dragging ? "border-link bg-raised" : "border-field bg-raised/60 hover:border-ink/60 hover:bg-raised"
          }`}
        >
          <input
            ref={inputRef}
            id="upload-file"
            type="file"
            accept={UPLOAD_ACCEPT}
            aria-describedby="upload-help"
            className="sr-only"
            onChange={(e) => onPicked(e.target.files?.[0])}
          />
          {file ? (
            <>
              <span className="font-display text-lg font-semibold text-ink">Ready to upload</span>
              <span className="break-all font-mono text-sm text-ink">{file.name}</span>
              <span className="text-sm text-muted">
                {formatSize(file.size)}. Choose or drop another file to replace it.
              </span>
            </>
          ) : (
            <>
              <span className="font-display text-lg font-semibold text-ink">Choose a file or drop it here</span>
              <span className="text-sm text-muted">.txt, .md, .pdf or .pptx, up to 25 MB</span>
            </>
          )}
        </label>
        {fileError ? (
          <p role="alert" className="mt-2 text-sm text-danger">
            {fileError}
          </p>
        ) : null}
        <div id="upload-help" className="mt-2 space-y-0.5 text-sm text-muted">
          <p>Up to roughly 37,500 words of text; split longer documents.</p>
          <p>Files are redacted on the server before anything is stored.</p>
        </div>
        <details className="group mt-3 max-w-prose text-sm">
          <summary className="inline-flex min-h-target cursor-pointer items-center text-link hover:underline">
            How uploads work
          </summary>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-muted">
            <li>
              The filename is stored as-is and shown in citations, so keep sensitive details
              out of it.
            </li>
            <li>Uploading a name that already exists in this engagement replaces that document.</li>
            <li>Longer documents are refused rather than cut short.</li>
          </ul>
        </details>
      </div>

      <div className="max-w-[12rem]">
        <Field
          id="upload-clearance"
          label="Clearance"
          hint="The server enforces your clearance ceiling."
        >
          <input
            id="upload-clearance"
            type="number"
            min={MIN_CLEARANCE}
            max={MAX_CLEARANCE}
            aria-describedby="upload-clearance-hint"
            className={inputClass}
            value={clearance}
            onChange={(e) => setClearance(Number(e.target.value))}
          />
        </Field>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={loading || !file || !engagement} className="min-w-[8rem]">
          {loading ? "Uploading..." : "Upload"}
        </Button>
      </div>
      {loading ? (
        // The browser's fetch can't report upload progress, so this is an
        // honest "working" indicator rather than a percentage.
        <div className="space-y-1">
          <progress aria-label="Uploading and indexing" className="block h-2 w-full max-w-md accent-accent" />
          <Spinner label="Uploading, redacting and indexing. Large documents can take up to a minute." />
        </div>
      ) : null}

      {error ? <ErrorBanner error={error} /> : null}
      {result !== null ? (
        <p role="status" className="rounded-sm border border-ok bg-ok-bg px-4 py-3 text-sm text-ok">
          Ingested {result.chunks} chunk{result.chunks === 1 ? "" : "s"} from{" "}
          <span className="font-mono">{result.name}</span>.
        </p>
      ) : null}
    </form>
  );
}
