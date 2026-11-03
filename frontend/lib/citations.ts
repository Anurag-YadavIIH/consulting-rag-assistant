/**
 * Splits an answer into plain text and citation markers like "[2]". A marker
 * becomes a "cite" segment only if a citation with that number exists;
 * anything else ("[]", "[slide 1]", "[0]", "[99]" with no citation 99) stays
 * plain text. Pure and total: any string in, a list of segments out, so an
 * answer with no markers, or odd ones, can never crash the page.
 */

export type AnswerSegment =
  | { kind: "text"; text: string }
  | { kind: "cite"; number: number; text: string };

const MARKER = /\[(\d{1,4})\]/g;

export function parseCitationMarkers(
  answer: string,
  citationNumbers: Iterable<number>
): AnswerSegment[] {
  const known = new Set(citationNumbers);
  const segments: AnswerSegment[] = [];
  let last = 0;

  const pushText = (text: string) => {
    if (!text) return;
    const prev = segments[segments.length - 1];
    if (prev && prev.kind === "text") prev.text += text;
    else segments.push({ kind: "text", text });
  };

  for (const match of answer.matchAll(MARKER)) {
    const start = match.index ?? 0;
    const number = Number(match[1]);
    pushText(answer.slice(last, start));
    if (known.has(number)) {
      segments.push({ kind: "cite", number, text: match[0] });
    } else {
      pushText(match[0]);
    }
    last = start + match[0].length;
  }
  pushText(answer.slice(last));
  return segments;
}

/** The citation numbers the answer actually uses, in order of first use:
 * the quoted passages in extractive mode, otherwise the [n] markers in the
 * answer text that match a citation. */
export function usedCitationNumbers(
  answer: string,
  citations: { number: number }[],
  quotes: { number: number; text?: string }[] = []
): number[] {
  const known = new Set(citations.map((c) => c.number));
  const order: number[] = [];
  const add = (n: number) => {
    if (known.has(n) && !order.includes(n)) order.push(n);
  };
  if (quotes.length > 0) quotes.forEach((q) => add(q.number));
  else
    parseCitationMarkers(answer, known).forEach((s) => {
      if (s.kind === "cite") add(s.number);
    });
  return order;
}
