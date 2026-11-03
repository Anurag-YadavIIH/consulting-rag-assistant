/**
 * Theme choice: storage (including blocked storage), applying it to <html>,
 * the pre-paint public/theme-init.js, the theme control, uploads checks and
 * the logo.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { applyThemeChoice, readThemeChoice, saveThemeChoice, THEME_STORAGE_KEY } from "../lib/theme";
import { checkUploadFile, pickDroppedFile } from "../lib/uploads";
import { ThemeControl } from "../components/ThemeControl";
import { LogoMark, Wordmark } from "../components/Logo";

afterEach(() => vi.unstubAllGlobals());

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

function throwingStorage() {
  const boom = () => {
    throw new Error("SecurityError: storage is blocked");
  };
  return { getItem: boom, setItem: boom, removeItem: boom };
}

class FakeRoot {
  attrs = new Map<string, string>();
  setAttribute(k: string, v: string) {
    this.attrs.set(k, v);
  }
  removeAttribute(k: string) {
    this.attrs.delete(k);
  }
}

it("defaults to System, and saves and reads Light and Dark", () => {
  const storage = memoryStorage();
  vi.stubGlobal("window", { localStorage: storage });
  expect(readThemeChoice()).toBe("system");
  saveThemeChoice("dark");
  expect(storage.data.get(THEME_STORAGE_KEY)).toBe("dark");
  expect(readThemeChoice()).toBe("dark");
  saveThemeChoice("system");
  expect(storage.data.has(THEME_STORAGE_KEY)).toBe(false); // System stores nothing
  expect([...storage.data.keys()]).toEqual([]); // and nothing else is ever stored
});

it("ignores unexpected stored values", () => {
  const storage = memoryStorage();
  storage.setItem(THEME_STORAGE_KEY, "<script>");
  vi.stubGlobal("window", { localStorage: storage });
  expect(readThemeChoice()).toBe("system");
});

it("blocked storage falls back to System and never throws", () => {
  vi.stubGlobal("window", { localStorage: throwingStorage() });
  expect(readThemeChoice()).toBe("system");
  expect(() => saveThemeChoice("dark")).not.toThrow();
});

it("applying a choice sets or removes html[data-theme]", () => {
  const root = new FakeRoot();
  applyThemeChoice("dark", root as unknown as HTMLElement);
  expect(root.attrs.get("data-theme")).toBe("dark");
  applyThemeChoice("system", root as unknown as HTMLElement);
  expect(root.attrs.has("data-theme")).toBe(false);
});

// --- public/theme-init.js ---------------------------------------------------------------

const INIT = readFileSync(resolve(__dirname, "../public/theme-init.js"), "utf8");

function runInit(storage: unknown) {
  const root = new FakeRoot();
  new Function("window", "document", INIT)({ localStorage: storage }, { documentElement: root });
  return root;
}

it("theme-init.js applies a saved Light or Dark choice before paint", () => {
  const s = memoryStorage();
  s.setItem("consultrag-theme", "dark");
  expect(runInit(s).attrs.get("data-theme")).toBe("dark");
  s.setItem("consultrag-theme", "light");
  expect(runInit(s).attrs.get("data-theme")).toBe("light");
});

it("theme-init.js leaves System, junk values and blocked storage alone", () => {
  expect(runInit(memoryStorage()).attrs.size).toBe(0);
  const junk = memoryStorage();
  junk.setItem("consultrag-theme", "purple");
  expect(runInit(junk).attrs.size).toBe(0);
  expect(runInit(throwingStorage()).attrs.size).toBe(0);
});

it("theme-init.js uses the same storage key as lib/theme.ts", () => {
  expect(INIT).toContain(`"${THEME_STORAGE_KEY}"`);
});

// --- the theme control --------------------------------------------------------------------

it("the theme control is a labelled radio group defaulting to System", () => {
  const html = renderToStaticMarkup(createElement(ThemeControl));
  expect(html).toContain("<fieldset");
  expect(html).toContain("<legend");
  expect(html.match(/type="radio"/g)).toHaveLength(3);
  expect(html).toMatch(/<input[^>]*checked=""[^>]*value="system"/);
  expect(html.match(/checked=""/g)).toHaveLength(1);
  for (const label of ["Light", "Dark", "System"]) expect(html).toContain(label);
});

// --- uploads: the same checks for picked and dropped files -------------------------------

it("upload checks accept supported files and refuse the rest", () => {
  expect(checkUploadFile({ name: "deck.PPTX", size: 1000 })).toBeNull();
  expect(checkUploadFile({ name: "notes.md", size: 10 })).toBeNull();
  expect(checkUploadFile({ name: "sheet.csv", size: 10 })).toMatch(/Unsupported file type \(\.csv\)/);
  expect(checkUploadFile({ name: "noextension", size: 10 })).toMatch(/Unsupported file type\./);
  expect(checkUploadFile({ name: "empty.txt", size: 0 })).toBe("That file is empty.");
  expect(checkUploadFile({ name: "big.pdf", size: 25 * 1024 * 1024 + 1 })).toMatch(/25 MB/);
  expect(checkUploadFile({ name: "edge.pdf", size: 25 * 1024 * 1024 })).toBeNull();
});

it("dropping applies the same checks, one file at a time", () => {
  expect(pickDroppedFile([{ name: "a.txt", size: 5 }])).toEqual({ file: { name: "a.txt", size: 5 }, error: null });
  expect(pickDroppedFile([{ name: "a.exe", size: 5 }]).error).toMatch(/Unsupported/);
  expect(pickDroppedFile([{ name: "a.txt", size: 5 }, { name: "b.txt", size: 5 }]).error).toBe(
    "Drop one file at a time."
  );
  expect(pickDroppedFile([])).toEqual({ file: null, error: null });
  expect(pickDroppedFile(null)).toEqual({ file: null, error: null });
});

// --- logo -----------------------------------------------------------------------------------

it("the logo mark has an accessible name when it stands alone, and is hidden in the wordmark", () => {
  const alone = renderToStaticMarkup(createElement(LogoMark, { title: "ConsultRAG" }));
  expect(alone).toContain('role="img"');
  expect(alone).toContain('aria-label="ConsultRAG"');
  const word = renderToStaticMarkup(createElement(Wordmark, {}));
  expect(word).toContain('aria-hidden="true"');
  expect(word.replace(/<[^>]+>/g, "")).toBe("ConsultRAG");
});

it("public/logo.svg and favicon.svg match the inline mark and have a title", () => {
  const inline = renderToStaticMarkup(createElement(LogoMark, {}));
  const rects = (s: string) => (s.match(/<rect[^>]*>/g) ?? []).map((r) => r.replace(/\s*\/?>$/, ""));
  for (const file of ["logo.svg", "favicon.svg"]) {
    const svg = readFileSync(resolve(__dirname, "../public", file), "utf8");
    expect(svg).toContain("<title");
    expect(rects(svg)).toEqual(rects(inline));
  }
});
