/**
 * Example questions, written for specific engagements from the sample and
 * demo documents in this repository (data/sample/, data/demo/). Any other
 * engagement gets no examples rather than ones that wouldn't match its
 * documents.
 */
const EXAMPLES: Record<string, string[]> = {
  // From data/sample/deck.pptx (slide and speaker notes), which a clearance 1
  // user can see. acme_research.txt is clearance 2 in the local data, so
  // questions only it answers aren't offered here.
  acme: [
    "What is the TAM for ambulatory neurosurgery?",
    "What reimbursement concerns were flagged?",
    "What is driving growth in this market?",
  ],
  meridian: [
    "Why did the outpatient scheduling pilot miss its target?",
    "What did the payer review say about reimbursement timing?",
  ],
  kestrel: [
    "How long is the sterilisation cycle on the new instrument tray?",
    "Which hospitals are in the first wave of the rollout?",
  ],
};

export function exampleQuestionsFor(engagement: string | undefined): string[] {
  if (!engagement) return [];
  return Object.prototype.hasOwnProperty.call(EXAMPLES, engagement) ? EXAMPLES[engagement] : [];
}
