import type { ActivityEvent } from "../../lib/api";

const EVENT_LABELS: Record<string, string> = {
  ingest: "Upload",
  delete: "Deletion",
  query: "Question",
  access: "Access change",
};

export function eventLabel(event: string): string {
  return EVENT_LABELS[event] ?? event;
}

/** A plain-language summary of an event's counts. No question text exists
 * in the audit log to show. */
export function eventDetails(e: ActivityEvent): string {
  if (e.event === "query") {
    const parts = [`${e.n_retrieved ?? 0} passage${e.n_retrieved === 1 ? "" : "s"} returned`];
    if (e.n_blocked) parts.push(`${e.n_blocked} withheld by access rules`);
    return parts.join(", ");
  }
  if (e.event === "ingest" || e.event === "delete") {
    const parts = [`${e.n_chunks ?? 0} chunk${e.n_chunks === 1 ? "" : "s"}`];
    const red = e.redaction_counts ?? {};
    const total = Object.values(red).reduce((a, b) => a + b, 0);
    if (total) parts.push(`${total} item${total === 1 ? "" : "s"} redacted`);
    return parts.join(", ");
  }
  return "";
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Audit events, newest first. Users appear by their internal ID only. */
export function ActivityTable({ events }: { events: ActivityEvent[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
        <caption className="sr-only">Recent activity, newest first</caption>
        <thead>
          <tr className="border-b border-rule text-muted">
            <th scope="col" className="py-2 pr-4 font-medium">When</th>
            <th scope="col" className="py-2 pr-4 font-medium">Event</th>
            <th scope="col" className="py-2 pr-4 font-medium">User</th>
            <th scope="col" className="py-2 pr-4 font-medium">Engagement</th>
            <th scope="col" className="py-2 pr-4 font-medium">Document</th>
            <th scope="col" className="py-2 font-medium">Details</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id} className="border-b border-rule align-top last:border-b-0">
              <td className="whitespace-nowrap py-2 pr-4 text-muted">{formatTime(e.ts)}</td>
              <td className="py-2 pr-4 text-ink">{eventLabel(e.event)}</td>
              <td className="py-2 pr-4 font-mono text-ink">{e.user_id}</td>
              <td className="py-2 pr-4 font-mono text-ink">{e.engagement ?? ""}</td>
              <td className="max-w-[14rem] break-all py-2 pr-4 font-mono text-ink">{e.document ?? ""}</td>
              <td className="py-2 text-muted">{eventDetails(e)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
