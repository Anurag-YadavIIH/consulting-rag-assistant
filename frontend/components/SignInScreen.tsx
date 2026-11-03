"use client";

import { useEffect, useRef, useState } from "react";
import { isGoogleSignInConfigured, renderGoogleSignInButton } from "../lib/auth";
import { Wordmark } from "./Logo";

/** Shown whenever there's no session. Renders no app data. */
export function SignInScreen({
  onCredential,
  error,
  busy = false,
}: {
  onCredential: (idToken: string) => void;
  error?: string | null;
  busy?: boolean;
}) {
  const buttonRef = useRef<HTMLDivElement>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const configured = isGoogleSignInConfigured();

  useEffect(() => {
    if (!configured || !buttonRef.current) return;
    renderGoogleSignInButton(buttonRef.current, onCredential).catch((e: unknown) =>
      setLoadError(e instanceof Error ? e.message : "Couldn't load Google sign-in.")
    );
  }, [configured, onCredential]);

  return (
    <div className="flex min-h-screen items-center justify-center p-4 sm:p-6">
      <div className="w-full max-w-md border border-rule bg-panel">
        <div className="on-dark flex items-center bg-side-bg px-6 py-5">
          <Wordmark surface="dark" size={28} />
        </div>
        <div className="space-y-5 px-6 py-7 text-center">
          <div>
            <h1 className="text-xl font-semibold text-ink">Evidence-cited answers</h1>
            <p className="mt-1 text-base text-muted">Sign in with your Google account to continue.</p>
          </div>
          {configured ? (
            <div ref={buttonRef} className="flex min-h-target justify-center" data-testid="google-button" />
          ) : (
            <div className="rounded-sm border border-field bg-raised px-3 py-2 text-sm text-ink">
              Google sign-in isn&apos;t configured. Set NEXT_PUBLIC_GOOGLE_CLIENT_ID and rebuild.
            </div>
          )}
          {busy ? <p role="status" className="text-sm text-muted">Signing in...</p> : null}
          {error || loadError ? (
            <div role="alert" className="rounded-sm border border-danger bg-danger-bg px-3 py-2 text-sm text-danger">
              {error ?? loadError}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
