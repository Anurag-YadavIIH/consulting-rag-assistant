"use client";

import { useMeContext } from "../lib/meContext";
import { QueryPanel } from "../components/QueryPanel";
import { IngestPanel } from "../components/IngestPanel";

export default function HomePage() {
  const { engagement } = useMeContext();

  return (
    <div className="max-w-3xl space-y-10">
      <section>
        <h1 className="text-lg font-semibold text-slate-800 mb-4">Ask a question</h1>
        <QueryPanel engagement={engagement} />
      </section>

      <section>
        <h2 className="text-lg font-semibold text-slate-800 mb-4">Ingest a document</h2>
        <IngestPanel engagement={engagement} />
      </section>
    </div>
  );
}
