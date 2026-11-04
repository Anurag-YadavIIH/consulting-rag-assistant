"use client";

import { useEffect, useRef, useState } from "react";
import { isGoogleSignInConfigured, renderGoogleSignInButton } from "../lib/auth";
import { Wordmark } from "./Logo";
import { HowItWorks } from "./signin/HowItWorks";

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
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <section className="on-dark flex flex-col justify-between gap-10 bg-side-bg px-6 py-8 sm:px-10 lg:px-14 lg:py-12">
        <Wordmark surface="dark" size={28} />
        <div className="max-w-3xl">
          <h1 className="font-display text-[34px] font-bold leading-tight tracking-tight text-side-text sm:text-[44px]">
            Find the answer. Keep client details private.
          </h1>
          <HowItWorks />
        </div>
        <p className="text-sm text-side-muted">Answers come only from documents your team uploads.</p>
      </section>

      <section className="order-first flex items-center justify-center bg-ground px-4 py-10 sm:px-6 lg:order-none">
        <div className="w-full max-w-sm space-y-6 border border-rule bg-panel px-6 py-8">
          <div className="lg:hidden">
            <Wordmark size={24} />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-ink">Sign in</h2>
            <p className="mt-1 text-base text-muted">Sign in with your Google account to continue.</p>
          </div>
          {configured ? (
            <div ref={buttonRef} className="flex min-h-target justify-center" data-testid="google-button" />
          ) : (
            <div className="rounded-sm border border-field bg-raised px-3 py-2 text-sm text-ink">
              Google sign-in isn&apos;t configured. Set NEXT_PUBLIC_GOOGLE_CLIENT_ID and rebuild.
            </div>
          )}
          {busy ? (
            <p role="status" className="text-sm text-muted">
              Signing in...
            </p>
          ) : null}
          {error || loadError ? (
            <div role="alert" className="rounded-sm border border-danger bg-danger-bg px-3 py-2 text-sm text-danger">
              {error ?? loadError}
            </div>
          ) : null}
          <p className="text-xs text-muted">
            New here? An administrator needs to give your account access before you can see
            any documents.
          </p>
        </div>
      </section>
    </div>
  );
}
