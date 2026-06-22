"use client";

import { useMeContext } from "../../lib/meContext";

/**
 * This page's visibility is decided ENTIRELY by what /me reports
 * (is_admin / clearance) — it is convenience, not security. Hiding this
 * route's nav link in AppShell, or showing the no-access message below
 * for a non-admin who navigates here directly, does not stop anyone:
 * the backend enforces clearance/engagement membership on every endpoint
 * regardless of what this page renders. If a future "management" API
 * endpoint is added, it must perform its own server-side authorization
 * check — this page must never be the only gate.
 */
export default function ManagementPage() {
  const { meInfo } = useMeContext();

  // Threshold matches AppShell's MANAGEMENT_CLEARANCE_THRESHOLD: 2 is the
  // highest non-admin clearance actually in use (scripts/seed_authz.py).
  const hasAccess = meInfo.is_admin || meInfo.clearance >= 2;

  if (!hasAccess) {
    return (
      <div className="max-w-md">
        <div className="rounded-md border border-amber-300 bg-amber-50 text-amber-800 px-4 py-3 text-sm">
          You don&apos;t have access to this engagement.
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <h1 className="text-lg font-semibold text-slate-800 mb-4">Management</h1>
      <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">
        Document inventory and audit views go here once a backend endpoint
        exists for them. No such endpoint is built yet — this is a
        placeholder, not a feature.
      </div>
    </div>
  );
}
