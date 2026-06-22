/**
 * lib/api.ts tests — fetch mocked, fully offline. Does NOT render any
 * component; this only covers the HTTP client functions, mirroring
 * tests/test_api_client.py's coverage of the Streamlit client.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ConnectionError,
  ForbiddenError,
  NotAuthenticatedError,
  ServerError,
  ingest,
  me,
  query,
} from "../lib/api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- happy paths ------------------------------------------------------------

it("me() parses a happy-path response", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      jsonResponse(200, {
        user_id: "1",
        engagements: ["acme"],
        is_admin: false,
        clearance: 2,
      })
    )
  );
  const result = await me();
  expect(result.user_id).toBe("1");
  expect(result.engagements).toEqual(["acme"]);
  expect(result.is_admin).toBe(false);
  expect(result.clearance).toBe(2);
});

it("query() parses a happy-path response with citations", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      jsonResponse(200, {
        answer: "The barrier is reimbursement uncertainty.",
        citations: [
          { source_path: "data/sample/acme.txt", locator: "", score: 0.83 },
        ],
      })
    )
  );
  const result = await query("What is the barrier?", "acme");
  expect(result.answer).toBe("The barrier is reimbursement uncertainty.");
  expect(result.citations).toHaveLength(1);
  expect(result.citations[0].source_path).toBe("data/sample/acme.txt");
  expect(result.citations[0].score).toBe(0.83);
});

it("query() handles an empty citations list", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      jsonResponse(200, { answer: "No accessible material matched.", citations: [] })
    )
  );
  const result = await query("anything");
  expect(result.citations).toEqual([]);
});

it("ingest() parses a happy-path response", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(jsonResponse(200, { chunks_ingested: 4 }))
  );
  const result = await ingest("data/sample", "acme", 2);
  expect(result.chunks_ingested).toBe(4);
});

// --- typed error surfacing ---------------------------------------------------

it("me() raises NotAuthenticatedError on 401", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse(401, { detail: "missing Authorization header" })
      )
    )
  );
  await expect(me()).rejects.toThrow(NotAuthenticatedError);
  await expect(me()).rejects.toMatchObject({
    status: 401,
    detail: "missing Authorization header",
  });
});

it("query() raises ForbiddenError on 403", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      jsonResponse(403, { detail: "not a member of this engagement" })
    )
  );
  await expect(query("anything", "globex")).rejects.toThrow(ForbiddenError);
});

it("ingest() raises ForbiddenError on 403", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      jsonResponse(403, { detail: "cannot ingest at a clearance above your own" })
    )
  );
  await expect(ingest("data/sample", "acme", 99)).rejects.toThrow(ForbiddenError);
});

it("query() raises ServerError on 500", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(jsonResponse(500, { detail: "internal error" }))
  );
  await expect(query("anything")).rejects.toThrow(ServerError);
});

it("me() raises ServerError on 503", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(jsonResponse(503, { detail: "service unavailable" }))
  );
  await expect(me()).rejects.toThrow(ServerError);
});

// --- transport-level failure (the API isn't running at all) -----------------

it("me() raises ConnectionError when fetch itself fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("fetch failed"))
  );
  await expect(me()).rejects.toThrow(ConnectionError);
});

it("query() raises ConnectionError when fetch itself fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("fetch failed"))
  );
  await expect(query("anything")).rejects.toThrow(ConnectionError);
});

it("error detail falls back to raw text when the body is not JSON", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response("not json", { status: 401 })
    )
  );
  await expect(me()).rejects.toMatchObject({ detail: "not json" });
});
