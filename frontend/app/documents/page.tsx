"use client";

import { useCallback, useEffect, useState } from "react";
import { deleteDocument, listDocuments, type DocumentInfo } from "../../lib/api";
import { useMeContext } from "../../lib/meContext";
import { IngestPanel } from "../../components/IngestPanel";
import { DocumentList } from "../../components/documents/DocumentList";
import { ErrorBanner } from "../../components/ErrorBanner";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Panel } from "../../components/ui/Panel";

/**
 * Documents: the engagement's document list (GET /documents), delete with
 * confirmation (DELETE /documents) and upload. The server decides what each
 * user sees and may delete; a document they can't see is never listed, and
 * deleting one answers like a missing document.
 */
export default function DocumentsPage() {
  const { engagement } = useMeContext();
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState<DocumentInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!engagement) return;
    setLoading(true);
    setError(null);
    try {
      const res = await listDocuments(engagement);
      setDocuments(res.documents);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [engagement]);

  useEffect(() => {
    setDocuments(null);
    setNotice(null);
    void refresh();
  }, [refresh]);

  async function confirmDelete() {
    if (!pending || !engagement) return;
    setDeleting(true);
    setError(null);
    try {
      const res = await deleteDocument(engagement, pending.name);
      setNotice(`Deleted ${res.name} (${res.chunks_deleted} chunk${res.chunks_deleted === 1 ? "" : "s"}).`);
      setPending(null);
      await refresh();
    } catch (err) {
      setError(err);
      setPending(null);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="max-w-4xl space-y-8">
      <header>
        <h1 className="text-title text-ink">Documents</h1>
        <p className="mt-2 max-w-prose text-base text-muted">
          {engagement ? (
            <>
              Documents in <span className="font-mono text-ink">{engagement}</span> that you can see
              at your clearance.
            </>
          ) : (
            "Choose an engagement in the sidebar."
          )}
        </p>
      </header>

      {engagement ? (
        <Panel title="In this engagement">
          <div className="space-y-4">
            {notice ? (
              <p role="status" className="rounded-sm border border-ok bg-ok-bg px-4 py-2 text-sm text-ok">
                {notice}
              </p>
            ) : null}
            {error ? <ErrorBanner error={error} /> : null}
            <DocumentList engagement={engagement} documents={documents} loading={loading} onDelete={setPending} />
          </div>
        </Panel>
      ) : null}

      <Panel title="Upload a document">
        <IngestPanel engagement={engagement} onUploaded={() => void refresh()} />
      </Panel>

      <ConfirmDialog
        open={pending !== null}
        title="Delete this document?"
        confirmLabel="Delete document"
        busy={deleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPending(null)}
      >
        <p>
          <span className="break-all font-mono text-ink">{pending?.name}</span> will be removed from{" "}
          <span className="font-mono text-ink">{engagement}</span> for everyone. It stops appearing in
          answers straight away. This can&apos;t be undone; upload it again to restore it.
        </p>
      </ConfirmDialog>
    </div>
  );
}
