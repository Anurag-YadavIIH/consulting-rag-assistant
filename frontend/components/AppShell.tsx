"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { me, NotAuthenticatedError, type MeResponse } from "../lib/api";
import { loginWithGoogleCredential, LoginError, onSignedOut, signOut } from "../lib/auth";
import { MeContext } from "../lib/meContext";
import { ErrorBanner } from "./ErrorBanner";
import { SignInScreen } from "./SignInScreen";
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

export type ShellState =
  | { kind: "loading" }
  | { kind: "signedOut"; error?: string | null; busy?: boolean }
  | { kind: "error"; error: unknown }
  | { kind: "ready"; meInfo: MeResponse };

/** No engagement membership and not an admin: a signed-in account nobody
 * has granted anything yet. The API refuses its queries (403) as well. */
export function hasNoAccess(meInfo: MeResponse): boolean {
  return !meInfo.is_admin && meInfo.engagements.length === 0;
}

/** Engagements to offer. Admins with no explicit memberships get the
 * build-time fallback list (there's no endpoint listing all engagements
 * yet); everyone else gets exactly their memberships. */
export function engagementOptionsFor(meInfo: MeResponse): string[] {
  if (meInfo.engagements.length > 0) return meInfo.engagements;
  return meInfo.is_admin ? FALLBACK_ENGAGEMENTS : [];
}

export function NoAccessPanel({
  meInfo,
  onSignOut,
}: {
  meInfo: MeResponse;
  onSignOut: () => void;
}) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="max-w-md w-full space-y-4">
        <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <div className="font-medium">No access yet</div>
          <p className="mt-1">
            You&apos;re signed in, but your account hasn&apos;t been added to any
            engagement. Ask an administrator to grant you access, then reload this page.
          </p>
        </div>
        <UserPanel meInfo={meInfo} onSignOut={onSignOut} />
      </div>
    </div>
  );
}

/** What the shell renders for a given state. Pages (children) render ONLY
 * in the ready state for an account with access; every other state shows
 * no app data at all. */
export function ShellView({
  state,
  engagement,
  setEngagement,
  onCredential,
  onSignOut,
  children,
}: {
  state: ShellState;
  engagement: string | undefined;
  setEngagement: (engagement: string) => void;
  onCredential: (idToken: string) => void;
  onSignOut: () => void;
  children: React.ReactNode;
}) {
  if (state.kind === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-slate-400">
        Loading...
      </div>
    );
  }

  if (state.kind === "signedOut") {
    return <SignInScreen onCredential={onCredential} error={state.error} busy={state.busy} />;
  }

  if (state.kind === "error") {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="max-w-md w-full">
          <ErrorBanner error={state.error} />
        </div>
      </div>
    );
  }

  const { meInfo } = state;
  if (hasNoAccess(meInfo)) {
    return <NoAccessPanel meInfo={meInfo} onSignOut={onSignOut} />;
  }

  const engagementOptions = engagementOptionsFor(meInfo);
  const showManagementLink =
    meInfo.is_admin || meInfo.clearance >= MANAGEMENT_CLEARANCE_THRESHOLD;

  return (
    <MeContext.Provider
      value={{ meInfo, engagementOptions, engagement, setEngagement }}
    >
      <div className="min-h-screen flex">
        <aside className="w-64 border-r border-slate-200 bg-white p-4 space-y-4">
          <div className="font-semibold text-slate-800">ConsultRAG</div>
          <UserPanel meInfo={meInfo} onSignOut={onSignOut} />
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

export function AppShell({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ShellState>({ kind: "loading" });
  const [engagement, setEngagement] = useState<string | undefined>(undefined);

  const loadMe = useCallback(async () => {
    try {
      const res = await me();
      setEngagement(engagementOptionsFor(res)[0]);
      setState({ kind: "ready", meInfo: res });
    } catch (err) {
      if (err instanceof NotAuthenticatedError) {
        setState({ kind: "signedOut" });
      } else {
        setState({ kind: "error", error: err });
      }
    }
  }, []);

  useEffect(() => {
    // Any failed refresh or sign-out, from anywhere in the app, drops back
    // to the sign-in screen and unmounts every page.
    const unsubscribe = onSignedOut(() => {
      setEngagement(undefined);
      setState({ kind: "signedOut" });
    });
    // First load (including after a reload): /me with no access token gets
    // a 401, which authFetch turns into one refresh attempt via the cookie.
    void loadMe();
    return unsubscribe;
  }, [loadMe]);

  const onCredential = useCallback(
    async (idToken: string) => {
      setState({ kind: "signedOut", busy: true });
      try {
        await loginWithGoogleCredential(idToken);
      } catch (e) {
        setState({
          kind: "signedOut",
          error: e instanceof LoginError ? e.message : "Sign-in failed. Please try again.",
        });
        return;
      }
      await loadMe();
    },
    [loadMe]
  );

  const onSignOut = useCallback(() => {
    void signOut();
  }, []);

  return (
    <ShellView
      state={state}
      engagement={engagement}
      setEngagement={setEngagement}
      onCredential={onCredential}
      onSignOut={onSignOut}
    >
      {children}
    </ShellView>
  );
}
