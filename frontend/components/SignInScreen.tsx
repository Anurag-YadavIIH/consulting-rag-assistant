"use client";

import { useEffect, useRef, useState } from "react";
import { isGoogleSignInConfigured, renderGoogleSignInButton } from "../lib/auth";

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
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="max-w-sm w-full rounded-lg border border-slate-200 bg-white p-6 space-y-4 text-center">
        <div className="font-semibold text-slate-800">ConsultRAG</div>
        <p className="text-sm text-slate-600">Sign in with your Google account to continue.</p>
        {configured ? (
          <div ref={buttonRef} className="flex justify-center" data-testid="google-button" />
        ) : (
          <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Google sign-in isn&apos;t configured. Set NEXT_PUBLIC_GOOGLE_CLIENT_ID and rebuild.
          </div>
        )}
        {busy ? <p className="text-sm text-slate-500">Signing in...</p> : null}
        {error || loadError ? (
          <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
            {error ?? loadError}
          </div>
        ) : null}
      </div>
    </div>
  );
}
