/**
 * Thin typed wrapper around the ConsultRAG FastAPI backend — the ONLY place
 * in this app that calls fetch(). Components never construct a request
 * themselves; everything routes through query()/ingest()/me() below.
 *
 * Mirrors src/consultrag/api/schemas.py exactly. No invented fields — this
 * module holds no business logic and never talks to the DB, vector store,
 * or RAG engine directly; it only calls the API over HTTP.
 */

import { getAuthHeaders } from "./auth";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// --- types, mirroring src/consultrag/api/schemas.py ---------------------

export interface Citation {
  source_path: string;
  locator: string;
  score: number;
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

export interface MeResponse {
  user_id: string;
  engagements: string[];
  is_admin: boolean;
  clearance: number;
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
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: body !== undefined ? JSON.stringify(body) : undefined,
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
