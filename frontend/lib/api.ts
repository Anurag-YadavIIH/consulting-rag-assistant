/**
 * Thin typed wrapper around the ConsultRAG FastAPI backend — the ONLY place
 * in this app that calls fetch(). Components never construct a request
 * themselves; everything routes through query()/uploadDocument()/ingest()/me()
 * below.
 *
 * Mirrors src/consultrag/api/schemas.py exactly. No invented fields — this
 * module holds no business logic and never talks to the DB, vector store,
 * or RAG engine directly; it only calls the API over HTTP.
 */

import { authFetch } from "./auth";
import { API_BASE_URL } from "./config";

export { API_BASE_URL };

// --- types, mirroring src/consultrag/api/schemas.py ---------------------

export interface Citation {
  /** Matches the passage's [n] in the answer's context (1-based). Clickable
   * [n] in the answer text is only guaranteed in extractive mode, so the
   * source list must work even when the answer contains no numbers. */
  number: number;
  source_path: string;
  locator: string;
  score: number;
  /** Redacted passage text, from a chunk the caller may see. */
  text: string;
  // Future seam: a `date`/`is_stale` field belongs here once the live-data
  // layer (see ARCHITECTURE.md §8) exists and /query actually returns one.
  // Not built on the API side yet, so deliberately not added here.
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
}

export interface IngestResponse {
  chunks_ingested: number;
}

export interface UploadResponse extends IngestResponse {
  source_name: string;
}

/** GET /documents?engagement=... Documents the caller couldn't retrieve
 * (any chunk above their clearance) are left out entirely. */
export interface DocumentInfo {
  name: string;
  chunks: number;
  clearance: number;
  /** UTC ISO 8601, or null for documents ingested before upload times were kept. */
  uploaded_at: string | null;
}

export interface DocumentsResponse {
  engagement: string;
  documents: DocumentInfo[];
}

/** DELETE /documents?engagement=...&name=... A missing document and one the
 * caller can't see both return the same 404. */
export interface DeleteDocumentResponse {
  name: string;
  chunks_deleted: number;
}

/** GET /admin/activity (admins only). No question text is stored. */
export interface ActivityEvent {
  id: number;
  ts: string;
  event: "ingest" | "delete" | "query";
  user_id: string;
  engagement: string | null;
  document: string | null;
  n_chunks: number | null;
  redaction_counts: Record<string, number> | null;
  n_retrieved: number | null;
  n_blocked: number | null;
}

export interface ActivityResponse {
  events: ActivityEvent[];
  /** Pass as `before` for the next (older) page; null when there's no more. */
  next_before: number | null;
}

/** File types POST /ingest/upload accepts (the server is authoritative). */
export const UPLOAD_ACCEPT = ".txt,.md,.pdf,.pptx";

export interface MeResponse {
  user_id: string;
  engagements: string[];
  is_admin: boolean;
  clearance: number;
  email?: string;
}

// --- typed errors ---------------------------------------------------------

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API error ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export class NotAuthenticatedError extends ApiError {
  constructor(detail: string) {
    super(401, detail);
    this.name = "NotAuthenticatedError";
  }
}

export class ForbiddenError extends ApiError {
  constructor(detail: string) {
    super(403, detail);
    this.name = "ForbiddenError";
  }
}

export class ServerError extends ApiError {
  constructor(status: number, detail: string) {
    super(status, detail);
    this.name = "ServerError";
  }
}

/** The API could not be reached at all (connection refused, DNS failure,
 * timeout) — distinct from a server-side HTTP error status. Wraps a fetch
 * network failure so callers never have to catch a raw TypeError. */
export class ConnectionError extends ApiError {
  constructor(detail: string) {
    super(0, detail);
    this.name = "ConnectionError";
  }
}

// --- internal request helper ----------------------------------------------

async function errorDetail(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const body = JSON.parse(text);
    return typeof body?.detail === "string" ? body.detail : text;
  } catch {
    return text;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  // FormData goes as-is: the browser sets the multipart Content-Type
  // (with its boundary) itself, so it must not be overridden here.
  const isForm = body instanceof FormData;
  let res: Response;
  try {
    // authFetch (lib/auth.ts) adds the access token and handles one
    // refresh-and-retry on a 401.
    res = await authFetch(`${API_BASE_URL}${path}`, {
      method,
      headers: isForm ? {} : { "Content-Type": "application/json" },
      body: isForm
        ? body
        : body !== undefined
          ? JSON.stringify(body)
          : undefined,
    });
  } catch (e) {
    throw new ConnectionError(e instanceof Error ? e.message : String(e));
  }

  if (!res.ok) {
    const detail = await errorDetail(res);
    if (res.status === 401) throw new NotAuthenticatedError(detail);
    if (res.status === 403) throw new ForbiddenError(detail);
    if (res.status >= 500) throw new ServerError(res.status, detail);
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

// --- public calls ----------------------------------------------------------

export function me(): Promise<MeResponse> {
  return request<MeResponse>("GET", "/me");
}

export function query(
  question: string,
  engagement?: string
): Promise<QueryResponse> {
  return request<QueryResponse>("POST", "/query", {
    question,
    engagement: engagement ?? null,
    llm: "extractive",
  });
}

export function uploadDocument(
  file: File,
  engagement: string,
  clearance = 1
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("engagement", engagement);
  form.append("clearance", String(clearance));
  return request<UploadResponse>("POST", "/ingest/upload", form);
}

/** Path-based ingest. The API only serves this when APP_ENV is development
 * (404 otherwise); kept for local use. Prefer uploadDocument(). */
export function ingest(
  path: string,
  engagement: string,
  clearance = 1
): Promise<IngestResponse> {
  return request<IngestResponse>("POST", "/ingest", {
    path,
    engagement,
    clearance,
  });
}
