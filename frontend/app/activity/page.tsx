"use client";

import { useMeContext } from "../../lib/meContext";
import { EmptyState } from "../../components/ui/EmptyState";

/**
 * Activity: a placeholder. The API's GET /admin/activity (admins only,
 * enforced on the server) is ready; showing its events here is a later step,
 * so this page deliberately shows no rows.
 *
 * Hiding the page from non-admins is convenience only: the server refuses
 * /admin/activity to anyone who isn't an admin.
 */
export default function ActivityPage() {
  const { meInfo } = useMeContext();

  if (!meInfo.is_admin) {
    return (
      <div className="max-w-md">
        <EmptyState title="Admins only">
          Activity is available to administrators.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-8">
      <header>
        <h1 className="text-title text-ink">Activity</h1>
        <p className="mt-2 text-base text-muted">Recent uploads, deletions and questions, by user ID.</p>
      </header>
      <EmptyState title="Placeholder: activity isn't shown here yet">
        The audit trail is recorded on the server and will be listed on this page in a
        later version. Nothing below is real data, so nothing is shown.
      </EmptyState>
    </div>
  );
}
