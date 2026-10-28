// Cited answers with quote verification and refusals, ported from app/answer.py.
// Same prompt, same 0.05 early-refusal cutoff, same word-for-word quote check.

import type postgres from "postgres";
import { scopeQuestion } from "./scope.ts";
import { search, type Filters, type Hit } from "./search.ts";
import { isNonAnswer, normalize, parseJson } from "./text.ts";

// Llama 3.1 8B, the model Ollama runs locally (Q4 there, FP8 here). The non-FP8
// @cf/meta/llama-3.1-8b-instruct was retired from Workers AI on 2026-05-30.
export const LLM_MODEL = "@cf/meta/llama-3.1-8b-instruct-fp8";
const MIN_RERANK_SCORE = 0.05;
const TOP_K = 5;

const SYSTEM_PROMPT = `You answer questions about U.S. federal grant funding announcements.

Use ONLY the numbered passages you are given. Never use outside knowledge.

Rules:
1. Every fact in your answer must be supported by a quote copied word-for-word from a passage.
2. Each quote must be short (under 40 words), copied exactly, and cite the passage number it came from.
3. If the passages do not clearly answer the question, or they are about a different grant or
   program than the one asked about, set "answerable" to false and leave "answer" empty.
4. Keep the answer short and direct (1-3 sentences). Name the grant you are answering about.

Respond with JSON only, in exactly this format:
{"answerable": true, "answer": "...", "citations": [{"passage": 1, "quote": "exact words from passage 1"}]}`;

const REFUSAL_NO_PASSAGES = "I couldn't find anything relevant to this question in the grant documents.";
const REFUSAL_NOT_ANSWERABLE = "The grant documents I found don't answer this question.";
const REFUSAL_UNVERIFIED = "I couldn't find a supported answer to this question in the grant documents.";

export interface Citation {
  passage: number;
  quote: string;
  verified: boolean;
  title?: string;
  section?: string | null;
  page?: number;
  page_end?: number;
  opportunity_id?: number;
}

export interface Answer {
  question: string;
  answer: string;
  refused: boolean;
  refusal_reason: "out_of_scope" | "no_passages" | "not_answerable" | "unverified" | null;
  citations: Citation[];
  dropped_citations: Citation[];
  passages: Hit[];
  top_score: number | null;
  timings_ms: Record<string, number>;
  model: string;
  scope: { agencies: string[]; agency_codes: string[]; opportunity_ids: number[]; missing_program: string | null };
}

export function formatPassages(passages: Hit[]): string {
  return passages
    .map((p, i) => `[${i + 1}] Grant: ${p.title}${p.section ? ` | Section: ${p.section}` : ""}\n${p.text}`)
    .join("\n\n");
}

export function verify(citation: Record<string, unknown>, passages: Hit[]): Citation {
  const idx = Number.parseInt(String(citation.passage ?? ""), 10) || 0;
  const quote = String(citation.quote ?? "").trim();
  if (idx < 1 || idx > passages.length || normalize(quote).split(" ").filter(Boolean).length < 3) {
    return { passage: idx, quote, verified: false };
  }
  const p = passages[idx - 1];
  const verified = normalize(`${p.section ?? ""} ${p.text}`).includes(normalize(quote));
  // The Worker has no PDF parser, so cite the chunk's page range (the local app pinpoints the page).
  return {
    passage: idx, quote, verified, title: p.title, section: p.section,
    page: p.page_start, page_end: p.page_end, opportunity_id: p.opportunity_id,
  };
}

async function generate(ai: Ai, question: string, passages: Hit[]): Promise<unknown> {
  const messages = [
    { role: "system", content: SYSTEM_PROMPT },
    { role: "user", content: `Question: ${question}\n\nPassages:\n\n${formatPassages(passages)}` },
  ];
  const params = { messages, temperature: 0, max_tokens: 700 };
  try {
    const out = (await ai.run(LLM_MODEL, { ...params, response_format: { type: "json_object" } })) as {
      response: unknown;
    };
    return out.response;
  } catch {
    // Not every model supports JSON mode; the prompt still asks for JSON and parseJson is lenient.
    const out = (await ai.run(LLM_MODEL, params)) as { response: unknown };
    return out.response;
  }
}

export async function answerQuestion(sql: postgres.Sql, ai: Ai, question: string, filters: Filters = {}): Promise<Answer> {
  const timings: Record<string, number> = {};
  let start = Date.now();
  // Restrict the search to the agency/grant the question names, or refuse if it only names
  // agencies we have no grants from (scope.ts).
  const scope = await scopeQuestion(sql, question);
  const scopeInfo = { agencies: scope.agencies, agency_codes: scope.agency_codes, opportunity_ids: scope.opportunity_ids,
    missing_program: scope.missing_program };
  const base = { question, citations: [], dropped_citations: [], timings_ms: timings, model: LLM_MODEL, scope: scopeInfo };
  if (scope.refusal) {
    timings.retrieval = Date.now() - start;
    return { ...base, answer: scope.refusal, refused: true, refusal_reason: "out_of_scope", passages: [], top_score: null };
  }

  const scoped: Filters = {
    ...filters,
    agencyCodes: scope.agency_codes.length ? scope.agency_codes : filters.agencyCodes,
    opportunityIds: scope.opportunity_ids.length ? scope.opportunity_ids : filters.opportunityIds,
  };
  const passages = await search(sql, ai, question, { k: TOP_K, filters: scoped, method: "hybrid_rerank" });
  timings.retrieval = Date.now() - start;
  const top_score = passages.length ? passages[0].score : null;

  if (!passages.length || (top_score ?? 0) < MIN_RERANK_SCORE) {
    return { ...base, answer: REFUSAL_NO_PASSAGES, refused: true, refusal_reason: "no_passages", passages, top_score };
  }

  start = Date.now();
  const raw = await generate(ai, question, passages);
  timings.generation = Date.now() - start;
  let out: Record<string, unknown>;
  try {
    out = parseJson(raw);
  } catch {
    out = { answerable: false };
  }

  const answerText = String(out.answer ?? "").trim();
  if (!out.answerable || !answerText || isNonAnswer(answerText)) {
    return { ...base, answer: REFUSAL_NOT_ANSWERABLE, refused: true, refusal_reason: "not_answerable", passages, top_score };
  }

  const raws = Array.isArray(out.citations) ? out.citations : [];
  const checked = raws.filter((c) => c && typeof c === "object").map((c) => verify(c as Record<string, unknown>, passages));
  const good = checked.filter((c) => c.verified);
  const bad = checked.filter((c) => !c.verified);
  if (!good.length) {
    return { ...base, answer: REFUSAL_UNVERIFIED, refused: true, refusal_reason: "unverified",
      dropped_citations: bad, passages, top_score };
  }
  return { ...base, answer: answerText, refused: false, refusal_reason: null, citations: good,
    dropped_citations: bad, passages, top_score };
}
