"use client";

import { useCallback, useEffect, useState } from "react";
import { adminActivity, type ActivityEvent, type ActivityEventType } from "../../lib/api";
import { useMeContext } from "../../lib/meContext";
import { ActivityTable } from "../../components/activity/ActivityTable";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { Field } from "../../components/ui/Field";
import { Panel } from "../../components/ui/Panel";
import { Select } from "../../components/ui/Select";
import { Spinner } from "../../components/ui/Spinner";

const PAGE = 50;
const FILTERS: Array<{ value: "" | ActivityEventType; label: string }> = [
  { value: "", label: "All events" },
  { value: "ingest", label: "Uploads" },
  { value: "delete", label: "Deletions" },
  { value: "query", label: "Questions" },
  { value: "access", label: "Access changes" },
];

/**
 * Activity: real audit events from GET /admin/activity, newest first, with
 * "Load older" paging and an event-type filter. Hidden from non-admins in
 * the UI; the server refuses the request to anyone who isn't an admin.
 */
export default function ActivityPage() {
  const { meInfo } = useMeContext();
  const [filter, setFilter] = useState<"" | ActivityEventType>("");
  const [events, setEvents] = useState<ActivityEvent[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  // Starts true: the first page loads as soon as the page mounts.
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(
    async (before: number | null) => {
      setLoading(true);
      setError(null);
      try {
        const res = await adminActivity({ limit: PAGE, before, event: filter || null });
        setEvents((prev) => (before && prev ? [...prev, ...res.events] : res.events));
        setNext(res.next_before);
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    },
    [filter]
  );

  useEffect(() => {
    if (!meInfo.is_admin) return;
    setEvents(null);
    setNext(null);
    void load(null);
  }, [meInfo.is_admin, load]);

  if (!meInfo.is_admin) {
    return (
      <div className="max-w-md">
        <EmptyState title="Admins only">Activity is available to administrators.</EmptyState>
      </div>
    );
  }

  return (
    <div className="max-w-6xl space-y-8">
      <header>
        <h1 className="text-title text-ink">Activity</h1>
        <p className="mt-2 max-w-prose text-base text-muted">
          Uploads, deletions, questions and access changes, newest first. People appear by user number; the
          audit log never stores question text or email addresses.
        </p>
      </header>

      <Panel
        title="Recent events"
        actions={
          <div className="w-48">
            <Field id="activity-filter" label="Show">
              <Select
                id="activity-filter"
                value={filter}
                onChange={(e) => setFilter(e.target.value as "" | ActivityEventType)}
              >
                {FILTERS.map((f) => (
                  <option key={f.value} value={f.value}>
                    {f.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        }
      >
        <div className="space-y-4">
          {error ? <ErrorBanner error={error} /> : null}
          {events === null && loading ? <Spinner label="Loading activity..." /> : null}
          {events !== null && events.length === 0 ? (
            <EmptyState variant="calm" title="No events yet">
              Events appear here as people upload, delete and ask questions.
            </EmptyState>
          ) : null}
          {events !== null && events.length > 0 ? <ActivityTable events={events} /> : null}
          {next ? (
            <Button variant="secondary" disabled={loading} onClick={() => void load(next)}>
              {loading ? "Loading..." : "Load older"}
            </Button>
          ) : null}
        </div>
      </Panel>
    </div>
  );
}
