"use client";

import { useMeContext } from "../../lib/meContext";
import { IngestPanel } from "../../components/IngestPanel";
import { Panel } from "../../components/ui/Panel";

/**
 * Documents. For now this holds the existing upload form, moved here from
 * the Ask page. Listing and deleting documents (the API already has
 * GET/DELETE /documents) come in a later step.
 */
export default function DocumentsPage() {
  const { engagement } = useMeContext();
  return (
    <div className="max-w-3xl space-y-8">
      <header>
        <h1 className="text-title text-ink">Documents</h1>
        <p className="mt-2 max-w-prose text-base text-muted">
          Add documents to an engagement. A list of each engagement&apos;s documents will
          appear here in a later version.
        </p>
      </header>
      <Panel title="Upload a document">
        <IngestPanel engagement={engagement} />
      </Panel>
    </div>
  );
}
