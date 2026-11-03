/** Build-time configuration shared by lib/api.ts and lib/auth.ts. */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Google OAuth web client ID. Public (it identifies the app, it isn't a
 * secret); the API checks ID tokens against the same value (OAUTH_AUDIENCE). */
export const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
