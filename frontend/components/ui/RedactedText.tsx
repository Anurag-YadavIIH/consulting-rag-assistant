import { splitRedactions } from "../../lib/redaction";

/**
 * Renders untrusted text, drawing a dark labelled bar ("email removed") only
 * where the text contains a real redaction marker from the server's redactor.
 * The label comes from the marker type alone; the bar's text is what screen
 * readers read. Everything is React text (never HTML), so filenames and
 * passages can't inject markup. The outline (`redact-edge`) keeps the bar
 * visible on dark panels; `side-text` on `redact` is high contrast in both themes.
 */
export function RedactedText({ text }: { text: string }) {
  return (
    <>
      {splitRedactions(text).map((seg, i) =>
        seg.kind === "text" ? (
          <span key={i}>{seg.text}</span>
        ) : (
          <span
            key={i}
            title={`${seg.description[0].toUpperCase()}${seg.description.slice(1)} removed before storage`}
            data-redacted={seg.label}
            className="mx-0.5 inline-block whitespace-nowrap rounded-sm bg-redact px-1.5 align-baseline font-mono text-xs leading-5 text-side-text ring-1 ring-redact-edge"
          >
            {seg.barText}
          </span>
        )
      )}
    </>
  );
}
