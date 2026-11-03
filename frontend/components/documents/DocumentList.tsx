"use client";

import type { DocumentInfo } from "../../lib/api";
import { EmptyState } from "../ui/EmptyState";
import { Spinner } from "../ui/Spinner";

export function formatUploaded(iso: string | null): string {
  if (!iso) return "Not recorded";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Not recorded";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * One engagement's documents, as the API reports them for this user (a
 * document with anything above their clearance isn't listed at all).
 * Filenames are untrusted text, rendered as React text.
 */
export function DocumentList({
  engagement,
  documents,
  loading,
  onDelete,
}: {
  engagement: string;
  documents: DocumentInfo[] | null;
  loading: boolean;
  onDelete: (doc: DocumentInfo) => void;
}) {
  if (loading && documents === null) return <Spinner label="Loading documents..." />;
  if (documents === null) return null;
  if (documents.length === 0) {
    return (
      <EmptyState variant="calm" title="No documents yet">
        Upload a document below to start asking questions about{" "}
        <span className="font-mono text-ink">{engagement}</span>.
      </EmptyState>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] border-collapse text-left text-sm">
        <caption className="sr-only">Documents in {engagement}</caption>
        <thead>
          <tr className="border-b border-rule text-muted">
            <th scope="col" className="py-2 pr-4 font-medium">Document</th>
            <th scope="col" className="py-2 pr-4 font-medium">Chunks</th>
            <th scope="col" className="py-2 pr-4 font-medium">Clearance</th>
            <th scope="col" className="py-2 pr-4 font-medium">Uploaded</th>
            <th scope="col" className="py-2 font-medium"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {documents.map((d) => (
            <tr key={d.name} className="border-b border-rule last:border-b-0">
              <td className="max-w-[18rem] break-all py-2 pr-4 font-mono text-ink">{d.name}</td>
              <td className="py-2 pr-4 text-ink">{d.chunks}</td>
              <td className="py-2 pr-4 text-ink">{d.clearance}</td>
              <td className="py-2 pr-4 text-muted">{formatUploaded(d.uploaded_at)}</td>
              <td className="py-1 text-right">
                <button
                  type="button"
                  onClick={() => onDelete(d)}
                  aria-label={`Delete ${d.name}`}
                  className="inline-flex min-h-target items-center rounded-sm border border-transparent px-3 text-sm text-danger transition-colors hover:border-danger hover:bg-danger-bg"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
