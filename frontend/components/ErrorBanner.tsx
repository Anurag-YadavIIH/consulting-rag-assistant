import {
  ApiError,
  ConnectionError,
  ForbiddenError,
  NotAuthenticatedError,
  ServerError,
} from "../lib/api";
import { API_LOCATION_LABEL } from "../lib/config";

/**
 * The ONE place that turns a thrown api.ts error into copy a user sees.
 * Never renders the raw server `detail` for 403s (could echo internal
 * phrasing); never renders a raw stack trace for anything. Upload
 * validation errors (400/409/413/415/422) do show the server's detail:
 * those messages are written by the API for the user (e.g. "file is larger
 * than the 25 MB upload limit") and are rendered as text, never as HTML.
 */
const USER_FACING_STATUSES = new Set([400, 409, 413, 415, 422]);

export function ErrorBanner({ error }: { error: unknown }) {
  let message: string;
  let tone: "error" | "warning" = "error";

  if (error instanceof ConnectionError) {
    message = `Can't reach ${API_LOCATION_LABEL}. Is it running?`;
  } else if (error instanceof NotAuthenticatedError) {
    message = "Not signed in.";
  } else if (error instanceof ForbiddenError) {
    message = "You don't have access to this engagement.";
    tone = "warning";
  } else if (error instanceof ServerError && error.status === 504) {
    // CloudFront gave up waiting (its origin response timeout) and doesn't
    // retry POSTs. The API may still be working on the request.
    message =
      "The server took too long to respond. If you were uploading a document, " +
      "it may still finish processing: wait a minute and ask a question about it " +
      "before uploading again. Very large documents can take longer than the " +
      "time limit, so try a smaller file.";
    tone = "warning";
  } else if (error instanceof ServerError) {
    message = "Something went wrong on the server. Please try again.";
  } else if (error instanceof ApiError && USER_FACING_STATUSES.has(error.status)) {
    message = error.detail;
    tone = "warning";
  } else {
    message = "Request failed. Please try again.";
  }

  const toneClasses =
    tone === "warning"
      ? "border-field bg-raised text-ink"
      : "border-danger bg-danger-bg text-danger";

  return (
    <div role="alert" className={`rounded-sm border px-4 py-3 text-sm ${toneClasses}`}>
      {message}
    </div>
  );
}
