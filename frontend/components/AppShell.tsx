"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { me, type MeResponse } from "../lib/api";
import { MeContext } from "../lib/meContext";
import { ErrorBanner } from "./ErrorBanner";
import { UserPanel } from "./UserPanel";
import { EngagementSelector } from "./EngagementSelector";

const FALLBACK_ENGAGEMENTS = (
  process.env.NEXT_PUBLIC_FALLBACK_ENGAGEMENTS ?? ""
)
  .split(",")
  .map((e) => e.trim())
  .filter(Boolean);

// Clearance threshold above which the Management nav link is shown.
// 2, not 3: the levels actually seeded today are 0/1 (default) and 2
// (scripts/seed_authz.py's example, the highest non-admin tier in use) —
// no clearance-3 user exists anywhere in the codebase, so a threshold of
// 3 would only ever match is_admin and never reflect a real clearance
// tier. Cosmetic only — see app/management/page.tsx for why this hides
// nothing that the backend doesn't already enforce.
const MANAGEMENT_CLEARANCE_THRESHOLD = 2;

export function AppShell({ children }: { children: React.ReactNode }) {
  const [meInfo, setMeInfo] = useState<MeResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [engagement, setEngagement] = useState<string | undefined>(undefined);

  useEffect(() => {
    me()
      .then((res) => {
        setMeInfo(res);
        const options =
          res.engagements.length > 0 ? res.engagements : FALLBACK_ENGAGEMENTS;
        setEngagement(options[0]);
      })
      .catch((err) => setError(err));
  }, []);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="max-w-md w-full">
          <ErrorBanner error={error} />
        </div>
      </div>
    );
  }

  if (!meInfo) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-slate-400">
        Loading...
      </div>
    );
  }

  const engagementOptions =
    meInfo.engagements.length > 0 ? meInfo.engagements : FALLBACK_ENGAGEMENTS;

  const showManagementLink =
    meInfo.is_admin || meInfo.clearance >= MANAGEMENT_CLEARANCE_THRESHOLD;

  return (
    <MeContext.Provider
      value={{ meInfo, engagementOptions, engagement, setEngagement }}
    >
      <div className="min-h-screen flex">
        <aside className="w-64 border-r border-slate-200 bg-white p-4 space-y-4">
          <div className="font-semibold text-slate-800">ConsultRAG</div>
          <UserPanel meInfo={meInfo} />
          <EngagementSelector
            options={engagementOptions}
            value={engagement}
            onChange={setEngagement}
          />
          <nav className="space-y-1 pt-2 text-sm">
            <Link
              href="/"
              className="block rounded px-2 py-1 text-slate-600 hover:bg-slate-100"
            >
              Query
            </Link>
            {showManagementLink ? (
              <Link
                href="/management"
                className="block rounded px-2 py-1 text-slate-600 hover:bg-slate-100"
              >
                Management
              </Link>
            ) : null}
          </nav>
        </aside>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </MeContext.Provider>
  );
}
