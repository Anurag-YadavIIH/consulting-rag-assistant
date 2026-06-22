"use client";

/**
 * Shares the current user's /me result and selected engagement across the
 * app shell and every page. Populated once, client-side, by AppShell — no
 * component below it calls me() itself.
 */

import { createContext, useContext } from "react";
import type { MeResponse } from "./api";

export interface MeContextValue {
  meInfo: MeResponse;
  engagementOptions: string[];
  engagement: string | undefined;
  setEngagement: (engagement: string) => void;
}

export const MeContext = createContext<MeContextValue | null>(null);

export function useMeContext(): MeContextValue {
  const ctx = useContext(MeContext);
  if (!ctx) {
    throw new Error("useMeContext() called outside <AppShell>");
  }
  return ctx;
}
