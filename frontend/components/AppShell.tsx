"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { me, NotAuthenticatedError, type MeResponse } from "../lib/api";
import { loginWithGoogleCredential, LoginError, onSignedOut, signOut } from "../lib/auth";
import { MeContext } from "../lib/meContext";
import { ErrorBanner } from "./ErrorBanner";
import { SignInScreen } from "./SignInScreen";
import { UserPanel } from "./UserPanel";
import { EngagementSelector } from "./EngagementSelector";
import { Wordmark } from "./Logo";
import { ThemeControl } from "./ThemeControl";
import { Spinner } from "./ui/Spinner";

const FALLBACK_ENGAGEMENTS = (
  process.env.NEXT_PUBLIC_FALLBACK_ENGAGEMENTS ?? ""
)
  .split(",")
  .map((e) => e.trim())
  .filter(Boolean);

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

export interface NavItem {
  href: string;
  label: string;
}

/** Sidebar navigation. Activity is only offered to admins; the API's
 * /admin/activity is the real check (403 for everyone else). */
export function navItemsFor(meInfo: MeResponse): NavItem[] {
  const items: NavItem[] = [
    { href: "/", label: "Ask" },
    { href: "/documents/", label: "Documents" },
  ];
  if (meInfo.is_admin) items.push({ href: "/activity/", label: "Activity" });
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
  children,
}: {
  state: ShellState;
  engagement: string | undefined;
  setEngagement: (engagement: string) => void;
  onCredential: (idToken: string) => void;
  onSignOut: () => void;
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

  const engagementOptions = engagementOptionsFor(meInfo);
  const nav = navItemsFor(meInfo);

  return (
    <MeContext.Provider value={{ meInfo, engagementOptions, engagement, setEngagement }}>
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
            <EngagementSelector options={engagementOptions} value={engagement} onChange={setEngagement} />
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
