import { splitRedactions } from "../../lib/redaction";

/**
 * Renders untrusted text, drawing a dark bar only where the text contains a
 * real redaction marker from the server's redactor. Everything is React text
 * (never HTML), so filenames and passages can't inject markup. The bar's
 * outline (`redact-edge`) keeps it visible on dark panels.
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
            role="img"
            aria-label={`Redacted ${seg.description}`}
            title={`Redacted ${seg.description}`}
            data-redacted={seg.label}
            className="mx-0.5 inline-block h-[0.95em] w-[6ch] translate-y-[0.12em] bg-redact align-baseline ring-1 ring-redact-edge"
          />
        )
      )}
    </>
  );
}
