/** Build-time configuration shared by lib/api.ts and lib/auth.ts. */

/** Turns the configured value into the prefix every API path is appended to.
 * Unset means local development (the API on localhost:8000). "/" (or "")
 * means same origin: requests go to relative paths like "/me", as on AWS
 * where CloudFront serves the frontend and the API together. "/" exists
 * because PowerShell deletes a variable set to "", so an empty value can't
 * reliably reach the build. Trailing slashes are dropped. */
export function resolveApiBaseUrl(raw: string | undefined): string {
  return (raw ?? "http://localhost:8000").replace(/\/+$/, "");
}

export const API_BASE_URL = resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL);

/** How to name the API in messages: "" (same origin) has no useful URL. */
export const API_LOCATION_LABEL = API_BASE_URL === "" ? "this site's API" : `the API at ${API_BASE_URL}`;

/** Google OAuth web client ID. Public (it identifies the app, it isn't a
 * secret); the API checks ID tokens against the same value (OAUTH_AUDIENCE). */
export const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
