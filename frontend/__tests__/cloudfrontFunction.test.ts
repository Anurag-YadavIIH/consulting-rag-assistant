/**
 * The CloudFront Function that maps folder URLs to index.html on the S3
 * behavior (infra/terraform/functions/static_rewrite.js). Loads the exact file
 * Terraform deploys and runs its handler.
 */

import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

const FILE = resolve(__dirname, "../../infra/terraform/functions/static_rewrite.js");

type CfRequest = { uri: string; method: string; headers: Record<string, unknown> };
const handler = new Function(`${readFileSync(FILE, "utf8")}; return handler;`)() as (
  event: { request: CfRequest }
) => CfRequest;

function rewrite(uri: string): string {
  return handler({ request: { uri, method: "GET", headers: {} } }).uri;
}

it.each([
  ["/", "/"], // default root object handles it
  ["/management/", "/management/index.html"],
  ["/management", "/management/index.html"],
  ["/404/", "/404/index.html"],
  ["/_next/static/chunks/app/page-abc123.js", "/_next/static/chunks/app/page-abc123.js"],
  ["/_next/static/css/3036530ecf3a2acc.css", "/_next/static/css/3036530ecf3a2acc.css"],
  ["/index.html", "/index.html"],
  ["/favicon.ico", "/favicon.ico"],
  ["/index.txt", "/index.txt"],
])("%s -> %s", (input, expected) => {
  expect(rewrite(input)).toBe(expected);
});

it("stays under CloudFront Functions' 10 KB size limit", () => {
  expect(statSync(FILE).size).toBeLessThan(10 * 1024);
});
