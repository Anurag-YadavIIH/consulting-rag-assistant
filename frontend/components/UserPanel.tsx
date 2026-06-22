import type { MeResponse } from "../lib/api";

export function UserPanel({ meInfo }: { meInfo: MeResponse }) {
  return (
    <div className="rounded-lg bg-slate-50 border border-slate-200 p-4 text-sm">
      <div className="font-medium text-slate-500 uppercase text-xs tracking-wide mb-2">
        Signed in as
      </div>
      <div className="text-slate-800">
        <span className="font-mono text-xs bg-slate-200 rounded px-1.5 py-0.5">
          {meInfo.user_id}
        </span>
      </div>
      <div className="mt-2 text-slate-600">Clearance: {meInfo.clearance}</div>
      {meInfo.is_admin && meInfo.engagements.length === 0 ? (
        <div className="mt-1 inline-block rounded bg-indigo-100 text-indigo-700 text-xs font-medium px-2 py-0.5">
          Admin — all engagements
        </div>
      ) : meInfo.is_admin ? (
        <div className="mt-1 inline-block rounded bg-indigo-100 text-indigo-700 text-xs font-medium px-2 py-0.5">
          Admin
        </div>
      ) : null}
    </div>
  );
}
