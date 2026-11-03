import type { MeResponse } from "../lib/api";

export function UserPanel({
  meInfo,
  onSignOut,
}: {
  meInfo: MeResponse;
  onSignOut?: () => void;
}) {
  return (
    <div className="rounded-lg bg-slate-50 border border-slate-200 p-4 text-sm">
      <div className="font-medium text-slate-500 uppercase text-xs tracking-wide mb-2">
        Signed in as
      </div>
      <div className="text-slate-800 break-all">
        {meInfo.email ? meInfo.email : "Development user (no sign-in)"}
      </div>
      <div className="mt-1 text-slate-500 text-xs">
        User #{" "}
        <span className="font-mono bg-slate-200 rounded px-1.5 py-0.5">{meInfo.user_id}</span>
      </div>
      <div className="mt-2 text-slate-600">Clearance: {meInfo.clearance}</div>
      {meInfo.is_admin && meInfo.engagements.length === 0 ? (
        <div className="mt-1 inline-block rounded bg-indigo-100 text-indigo-700 text-xs font-medium px-2 py-0.5">
          Admin, all engagements
        </div>
      ) : meInfo.is_admin ? (
        <div className="mt-1 inline-block rounded bg-indigo-100 text-indigo-700 text-xs font-medium px-2 py-0.5">
          Admin
        </div>
      ) : null}
      {onSignOut ? (
        <button
          type="button"
          onClick={onSignOut}
          className="mt-3 block w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-slate-700 hover:bg-slate-100"
        >
          Sign out
        </button>
      ) : null}
    </div>
  );
}
