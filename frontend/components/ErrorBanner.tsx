import {
  API_BASE_URL,
  ConnectionError,
  ForbiddenError,
  NotAuthenticatedError,
  ServerError,
} from "../lib/api";

/**
 * The ONE place that turns a thrown api.ts error into copy a user sees.
 * Never renders the raw server `detail` for 403s (could echo internal
 * phrasing); never renders a raw stack trace for anything.
 */
export function ErrorBanner({ error }: { error: unknown }) {
  let message: string;
  let tone: "error" | "warning" = "error";

  if (error instanceof ConnectionError) {
    message = `Can't reach the API at ${API_BASE_URL} — is it running?`;
  } else if (error instanceof NotAuthenticatedError) {
    message = "Not signed in.";
  } else if (error instanceof ForbiddenError) {
    message = "You don't have access to this engagement.";
    tone = "warning";
  } else if (error instanceof ServerError) {
    message = "Something went wrong on the server. Please try again.";
  } else {
    message = "Request failed. Please try again.";
  }

  const toneClasses =
    tone === "warning"
      ? "bg-amber-50 border-amber-300 text-amber-800"
      : "bg-red-50 border-red-300 text-red-800";

  return (
    <div className={`rounded-md border px-4 py-3 text-sm ${toneClasses}`}>
      {message}
    </div>
  );
}
