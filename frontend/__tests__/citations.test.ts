import { expect, it } from "vitest";
import { parseCitationMarkers } from "../lib/citations";

it("turns markers that match a citation into cite segments", () => {
  expect(parseCitationMarkers("Growth is 12% [1] and TAM 2.4B [2].", [1, 2])).toEqual([
    { kind: "text", text: "Growth is 12% " },
    { kind: "cite", number: 1, text: "[1]" },
    { kind: "text", text: " and TAM 2.4B " },
    { kind: "cite", number: 2, text: "[2]" },
    { kind: "text", text: "." },
  ]);
});

it("keeps markers with no matching citation as text", () => {
  expect(parseCitationMarkers("See [3] and [1].", [1])).toEqual([
    { kind: "text", text: "See [3] and " },
    { kind: "cite", number: 1, text: "[1]" },
    { kind: "text", text: "." },
  ]);
});

it("ignores brackets that aren't numeric markers", () => {
  const answer = "[1] Source: deck.pptx [slide 1]\nnotes [] [x] [-1] [1.5]";
  const segs = parseCitationMarkers(answer, [1]);
  expect(segs.filter((s) => s.kind === "cite")).toEqual([{ kind: "cite", number: 1, text: "[1]" }]);
  expect(segs.map((s) => s.text).join("")).toBe(answer); // nothing lost or reordered
});

it("treats [0] and numbers beyond the list as plain text", () => {
  const segs = parseCitationMarkers("[0] [5] [12345]", [1, 2]);
  expect(segs).toEqual([{ kind: "text", text: "[0] [5] [12345]" }]);
});

it("an answer with no markers is one text segment", () => {
  expect(parseCitationMarkers("No markers here.", [1, 2])).toEqual([
    { kind: "text", text: "No markers here." },
  ]);
});

it("empty answers and empty citation lists don't crash", () => {
  expect(parseCitationMarkers("", [1])).toEqual([]);
  expect(parseCitationMarkers("[1]", [])).toEqual([{ kind: "text", text: "[1]" }]);
});

it("the same marker can appear twice", () => {
  const segs = parseCitationMarkers("[2] then [2]", [2]);
  expect(segs.filter((s) => s.kind === "cite")).toHaveLength(2);
});
