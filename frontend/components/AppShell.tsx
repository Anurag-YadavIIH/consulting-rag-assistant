"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { listEngagements, me, NotAuthenticatedError, type MeResponse } from "../lib/api";
import { loginWithGoogleCredential, LoginError, onSignedOut, signOut } from "../lib/auth";
import { MeContext } from "../lib/meContext";
import { ErrorBanner } from "./ErrorBanner";
import { SignInScreen } from "./SignInScreen";
import { UserPanel } from "./UserPanel";
import { EngagementSelector } from "./EngagementSelector";
import { Wordmark } from "./Logo";
import { ThemeControl } from "./ThemeControl";
import { Spinner } from "./ui/Spinner";

export type ShellState =
  | { kind: "loading" }
  | { kind: "signedOut"; error?: string | null; busy?: boolean }
  | { kind: "error"; error: unknown }
  | {
      kind: "ready";
      meInfo: MeResponse;
      /** Admins only: every engagement from GET /admin/engagements. */
      allEngagements?: string[];
      /** Admins only: that request failed; own memberships are still shown. */
      engagementsError?: unknown;
    };

/** No engagement membership and not an admin: a signed-in account nobody
 * has granted anything yet. The API refuses its queries (403) as well. */
export function hasNoAccess(meInfo: MeResponse): boolean {
  return !meInfo.is_admin && meInfo.engagements.length === 0;
}

/** Engagements to offer, sorted. Everyone gets their own memberships (from
 * /me). Admins also get every engagement the admin-only GET
 * /admin/engagements lists; non-admins never use that list. */
export function engagementOptionsFor(meInfo: MeResponse, allEngagements?: string[]): string[] {
  const names = new Set(meInfo.engagements);
  if (meInfo.is_admin) for (const e of allEngagements ?? []) names.add(e);
  return Array.from(names).sort();
}

/** The engagement to select: keep the current one while it's offered,
 * otherwise the first available (undefined when there are none). */
export function pickEngagement(options: string[], current: string | undefined): string | undefined {
  return current !== undefined && options.includes(current) ? current : options[0];
}

/** Admins: the full list from the admin-only GET /admin/engagements. A
 * failure is returned, not thrown, so the admin keeps their own memberships. */
export async function loadAllEngagements(): Promise<{ allEngagements?: string[]; engagementsError?: unknown }> {
  try {
    const { engagements } = await listEngagements();
    return { allEngagements: engagements, engagementsError: undefined };
  } catch (err) {
    return { allEngagements: undefined, engagementsError: err };
  }
}

/** After sign-in or a reload: /me for everyone, plus the admin list for
 * admins only. Throws what me() throws (e.g. NotAuthenticatedError). */
export async function loadSignedInState(): Promise<{ state: ShellState & { kind: "ready" }; engagement: string | undefined }> {
  const meInfo = await me();
  const extra = meInfo.is_admin ? await loadAllEngagements() : {};
  return {
    state: { kind: "ready", meInfo, ...extra },
    engagement: pickEngagement(engagementOptionsFor(meInfo, extra.allEngagements), undefined),
  };
}

export interface NavItem {
  href: string;
  label: string;
}

/** Sidebar navigation. Activity and Team are only offered to admins; the
 * API's /admin routes are the real check (403 for everyone else). */
export function navItemsFor(meInfo: MeResponse): NavItem[] {
  const items: NavItem[] = [
    { href: "/", label: "Ask" },
    { href: "/documents/", label: "Documents" },
  ];
  if (meInfo.is_admin) {
    items.push({ href: "/activity/", label: "Activity" });
    items.push({ href: "/team/", label: "Team" });
  }
  return items;
}

function isActive(href: string, pathname: string | null): boolean {
  if (!pathname) return false;
  const norm = (p: string) => (p.endsWith("/") ? p : `${p}/`);
  return href === "/" ? pathname === "/" : norm(pathname) === norm(href);
}

function CenteredPage({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-screen items-center justify-center p-4 sm:p-6">{children}</div>;
}

export function NoAccessPanel({
  meInfo,
  onSignOut,
}: {
  meInfo: MeResponse;
  onSignOut: () => void;
}) {
  return (
    <CenteredPage>
      <div className="w-full max-w-md space-y-4">
        <Wordmark />
        <div className="rounded-sm border border-field bg-panel px-5 py-5 text-sm">
          <h1 className="text-xl font-semibold text-ink">No access yet</h1>
          <p className="mt-2 text-muted">
            You&apos;re signed in, but your account hasn&apos;t been added to any
            engagement. Ask an administrator to grant you access, then reload this page.
          </p>
        </div>
        <UserPanel meInfo={meInfo} onSignOut={onSignOut} />
      </div>
    </CenteredPage>
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
  onRetryEngagements = () => {},
  onEngagementsLoaded = () => {},
  children,
}: {
  state: ShellState;
  engagement: string | undefined;
  setEngagement: (engagement: string) => void;
  onCredential: (idToken: string) => void;
  onSignOut: () => void;
  onRetryEngagements?: () => void;
  onEngagementsLoaded?: (engagements: string[]) => void;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  if (state.kind === "loading") {
    return (
      <CenteredPage>
        <Spinner label="Loading..." />
      </CenteredPage>
    );
  }

  if (state.kind === "signedOut") {
    return <SignInScreen onCredential={onCredential} error={state.error} busy={state.busy} />;
  }

  if (state.kind === "error") {
    return (
      <CenteredPage>
        <div className="w-full max-w-md">
          <ErrorBanner error={state.error} />
        </div>
      </CenteredPage>
    );
  }

  const { meInfo } = state;
  if (hasNoAccess(meInfo)) {
    return <NoAccessPanel meInfo={meInfo} onSignOut={onSignOut} />;
  }

  const engagementOptions = engagementOptionsFor(meInfo, state.allEngagements);
  const nav = navItemsFor(meInfo);

  return (
    <MeContext.Provider
      value={{ meInfo, engagementOptions, engagement, setEngagement, onEngagementsLoaded }}
    >
      <div className="min-h-screen lg:flex">
        {/* Phone and tablet: a top bar with a menu button. */}
        <div className="on-dark flex items-center justify-between border-b border-side-border bg-side-bg px-5 py-2 lg:hidden">
          <Wordmark surface="dark" size={22} />
          <button
            type="button"
            className="min-h-target min-w-target rounded-sm border border-side-border px-3 text-sm text-side-text transition-colors hover:bg-side-raised"
            aria-expanded={menuOpen}
            aria-controls="app-sidebar"
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? "Close menu" : "Menu"}
          </button>
        </div>

        <aside
          id="app-sidebar"
          aria-label="Main"
          className={`on-dark border-side-border bg-side-bg px-5 py-5 lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-72 lg:shrink-0 lg:flex-col lg:overflow-y-auto lg:border-r ${menuOpen ? "block" : "hidden"} lg:block`}
        >
          <div className="hidden lg:block">
            <Wordmark surface="dark" />
          </div>
          <div className="space-y-6 lg:mt-8 lg:flex lg:flex-1 lg:flex-col">
            <EngagementSelector
              options={engagementOptions}
              value={engagement}
              onChange={setEngagement}
              isAdmin={meInfo.is_admin}
              loadFailed={Boolean(state.engagementsError)}
              onRetry={onRetryEngagements}
            />
            <nav aria-label="Sections">
              <ul className="space-y-1">
                {nav.map((item) => {
                  const active = isActive(item.href, pathname);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        onClick={() => setMenuOpen(false)}
                        className={`flex min-h-target items-center rounded-sm px-3 text-base font-medium transition-colors ${
                          active ? "bg-accent text-on-accent" : "text-side-text hover:bg-side-raised"
                        }`}
                      >
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </nav>
            <div className="space-y-5 lg:mt-auto">
              <ThemeControl />
              <UserPanel meInfo={meInfo} onSignOut={onSignOut} dark />
            </div>
          </div>
        </aside>

        <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 lg:py-10">
          <div className="mx-auto w-full max-w-page">{children}</div>
        </main>
      </div>
    </MeContext.Provider>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ShellState>({ kind: "loading" });
  const [engagement, setEngagement] = useState<string | undefined>(undefined);

  const loadMe = useCallback(async () => {
    try {
      const loaded = await loadSignedInState();
      setEngagement(loaded.engagement);
      setState(loaded.state);
    } catch (err) {
      if (err instanceof NotAuthenticatedError) {
        setState({ kind: "signedOut" });
      } else {
        setState({ kind: "error", error: err });
      }
    }
  }, []);

  const retryEngagements = useCallback(async () => {
    if (state.kind !== "ready" || !state.meInfo.is_admin) return;
    const extra = await loadAllEngagements();
    setState((s) => (s.kind === "ready" ? { ...s, ...extra } : s));
  }, [state]);

  // The Team page already fetches the same list; it hands it over after each
  // change so a new engagement shows up without a reload.
  const onEngagementsLoaded = useCallback((engagements: string[]) => {
    setState((s) => (s.kind === "ready" && s.meInfo.is_admin ? { ...s, allEngagements: engagements, engagementsError: undefined } : s));
  }, []);

  // Keep a valid selection: the first available engagement when there's none
  // yet, or when the selected one is no longer offered.
  const options = state.kind === "ready" ? engagementOptionsFor(state.meInfo, state.allEngagements) : [];
  const optionsKey = options.join(",");
  useEffect(() => {
    const next = pickEngagement(options, engagement);
    if (next !== undefined && next !== engagement) setEngagement(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optionsKey, engagement]);

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
      onRetryEngagements={() => void retryEngagements()}
      onEngagementsLoaded={onEngagementsLoaded}
    >
      {children}
    </ShellView>
  );
}
