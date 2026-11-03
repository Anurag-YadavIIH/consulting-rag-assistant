import type { MeResponse } from "../lib/api";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";

/** The signed-in user. `dark` is the sidebar version; otherwise a panel. */
export function UserPanel({
  meInfo,
  onSignOut,
  dark = false,
}: {
  meInfo: MeResponse;
  onSignOut?: () => void;
  dark?: boolean;
}) {
  const text = dark ? "text-side-text" : "text-ink";
  const muted = dark ? "text-side-muted" : "text-muted";
  return (
    <div className={dark ? "border-t border-side-border pt-4" : "rounded-sm border border-rule bg-panel p-4"}>
      <p className={`text-xs ${muted}`}>Signed in as</p>
      <p className={`mt-0.5 break-all text-sm font-medium ${text}`}>
        {meInfo.email ? meInfo.email : "Development user (no sign-in)"}
      </p>
      <p className={`mt-1 flex flex-wrap items-center gap-x-2 text-xs ${muted}`}>
        <span>
          User # <span className="font-mono">{meInfo.user_id}</span>
        </span>
        <span aria-hidden="true">·</span>
        <span>Clearance {meInfo.clearance}</span>
        {meInfo.is_admin ? (
          <Badge tone={dark ? "sidebar" : "neutral"}>
            {meInfo.engagements.length === 0 ? "Admin, all engagements" : "Admin"}
          </Badge>
        ) : null}
      </p>
      {onSignOut ? (
        <Button variant={dark ? "sidebar" : "secondary"} className="mt-3 w-full" onClick={onSignOut}>
          Sign out
        </Button>
      ) : null}
    </div>
  );
}
