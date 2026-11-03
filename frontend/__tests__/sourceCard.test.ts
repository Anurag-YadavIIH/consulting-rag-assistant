/**
 * Uploaded filenames are user input and come back as citation source_path.
 * SourceCard must render them as text, never as markup. Rendered to static
 * HTML with react-dom/server, so no DOM test library is needed.
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { SourceCard } from "../components/SourceCard";

it("escapes a hostile filename in a citation", () => {
  const hostile = '<img src=x onerror="alert(1)">report.txt';
  const html = renderToStaticMarkup(
    createElement(SourceCard, {
      citation: {
        number: 1,
        source_path: hostile,
        locator: "<b>page 1</b>",
        score: 0.5,
        text: "<script>alert(1)</script> passage",
      },
    })
  );
  expect(html).not.toContain("<img");
  expect(html).not.toContain("<b>");
  expect(html).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;report.txt");
});
