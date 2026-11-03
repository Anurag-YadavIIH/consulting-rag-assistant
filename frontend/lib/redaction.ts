/**
 * Finds the redaction markers the server's redactor writes into stored text
 * (src/consultrag/security/redaction.py: "[REDACTED_<LABEL>]"). Only the exact
 * labels it can produce become redaction segments; a marker with any other
 * label stays plain text, so the UI never draws a bar the server didn't put
 * there.
 */

export const REDACTION_LABELS: Record<string, string> = {
  EMAIL: "email address",
  SSN: "social security number",
  CREDIT_CARD: "card number",
  PHONE: "phone number",
  MRN: "medical record number",
  NPI: "provider identifier",
  IP_ADDRESS: "IP address",
  CUSTOM: "client term",
};

export type TextSegment =
  | { kind: "text"; text: string }
  | { kind: "redacted"; label: string; description: string; text: string };

const MARKER = /\[REDACTED_([A-Z_]+)\]/g;

export function splitRedactions(text: string): TextSegment[] {
  const segments: TextSegment[] = [];
  let last = 0;

  const pushText = (t: string) => {
    if (!t) return;
    const prev = segments[segments.length - 1];
    if (prev && prev.kind === "text") prev.text += t;
    else segments.push({ kind: "text", text: t });
  };

  for (const match of text.matchAll(MARKER)) {
    const start = match.index ?? 0;
    const label = match[1];
    pushText(text.slice(last, start));
    const description = Object.prototype.hasOwnProperty.call(REDACTION_LABELS, label)
      ? REDACTION_LABELS[label]
      : undefined;
    if (description) {
      segments.push({ kind: "redacted", label, description, text: match[0] });
    } else {
      pushText(match[0]);
    }
    last = start + match[0].length;
  }
  pushText(text.slice(last));
  return segments;
}
