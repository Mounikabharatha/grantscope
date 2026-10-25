// Text helpers, ported 1:1 from the Python app (app/evaluation.py, app/answer.py, app/llm.py)
// so the deployed Worker verifies quotes exactly like the evaluated local pipeline.

/** Lowercase, NFKC (turns PDF ligatures like "ﬁ" into "fi"), keep only letters/digits. */
export function normalize(text: string): string {
  return (text.normalize("NFKC").toLowerCase().match(/[a-z0-9]+/g) ?? []).join(" ");
}

// "X is not mentioned in the passages": a claim that something is missing AND a reference to
// the source. Real answers like "For-profit hospitals are not eligible" don't match.
const NON_ANSWER_CLAIM =
  /\b(no|not|isn't|aren't|doesn't|don't)\b\W+(?:\w+\W+){0,3}?(mention(ed)?|provided?|stated?|specif(y|ied|ies)|available|include[sd]?|found|says?)\b/i;
const NON_ANSWER_SOURCE = /\b(passages?|documents?|context|provided text)\b/i;

export function isNonAnswer(text: string): boolean {
  return NON_ANSWER_CLAIM.test(text) && NON_ANSWER_SOURCE.test(text);
}

/** Parse a JSON object, tolerating stray text around it (or an already-parsed object). */
export function parseJson(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object") return value as Record<string, unknown>;
  const text = String(value ?? "");
  try {
    return JSON.parse(text);
  } catch {
    const match = text.match(/\{[\s\S]*\}/);
    if (match) return JSON.parse(match[0]);
    throw new Error("model did not return JSON");
  }
}
