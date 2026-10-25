// Retrieval, ported from app/search.py: vector (pgvector HNSW), keyword (Postgres full-text),
// hybrid (Reciprocal Rank Fusion), and cross-encoder reranking. Same SQL, same defaults
// (RRF k=60, 50 candidates per list, rerank top 30) as the evaluated Python version.

import type postgres from "postgres";

export const EMBEDDING_MODEL = "@cf/baai/bge-small-en-v1.5";
export const RERANKER_MODEL = "@cf/baai/bge-reranker-base";
// BGE v1.5 is trained with this instruction on queries (not passages); same as app/embeddings.py.
const QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: ";

const RRF_K = 60;
const CANDIDATES = 50;
const RERANK_CANDIDATES = 30;
export const METHODS = ["vector", "keyword", "hybrid", "vector_rerank", "hybrid_rerank"] as const;
export type Method = (typeof METHODS)[number];

export interface Filters {
  agency?: string;
  minAward?: number;
  openOn?: string; // YYYY-MM-DD
  agencyCodes?: string[]; // set by scope.ts from the question
  opportunityIds?: number[]; // set by scope.ts from the question
}

export interface Hit {
  chunk_id: string;
  opportunity_id: number;
  section: string | null;
  page_start: number;
  page_end: number;
  text: string;
  title: string;
  agency_code: string;
  award_ceiling: number | null;
  close_date: string | null;
  source_url: string;
  score: number;
}

type Sql = postgres.Sql | postgres.TransactionSql;

// Casts keep the JSON identical to the Python API (ints, plain date strings).
const COLUMNS = `c.chunk_id, c.opportunity_id::int AS opportunity_id, c.section, c.page_start, c.page_end,
  c.text, d.title, d.agency_code, d.award_ceiling::float8 AS award_ceiling,
  d.close_date::text AS close_date, d.source_url`;

function filterSql(sql: Sql, f: Filters) {
  return sql`
    ${f.agency ? sql`AND d.agency_code = ${f.agency}` : sql``}
    ${f.minAward != null ? sql`AND d.award_ceiling >= ${f.minAward}` : sql``}
    ${f.openOn ? sql`AND d.close_date >= ${f.openOn}::date` : sql``}
    ${f.agencyCodes?.length ? sql`AND d.agency_code = ANY(string_to_array(${f.agencyCodes.join(",")}, ','))` : sql``}
    ${f.opportunityIds?.length
      ? sql`AND d.opportunity_id = ANY(string_to_array(${f.opportunityIds.join(",")}, ',')::bigint[])` : sql``}`;
// Lists go in as comma-joined text: with fetch_types off, postgres.js can't serialize JS arrays
// ("malformed array literal"). Agency codes and ids never contain commas.
}

export async function embedQuery(ai: Ai, query: string): Promise<string> {
  // pooling "cls" matches sentence-transformers' pooling for this model, which produced the
  // stored chunk embeddings; Workers AI defaults to "mean", which would not line up.
  const out = (await ai.run(EMBEDDING_MODEL, { text: [QUERY_INSTRUCTION + query], pooling: "cls" })) as {
    data: number[][];
  };
  return `[${out.data[0].join(",")}]`;
}

export async function vectorSearch(sql: postgres.Sql, ai: Ai, query: string, chunkSet: string, k: number, f: Filters) {
  const vec = await embedQuery(ai, query);
  return sql.begin(async (tx) => {
    // With filters, HNSW may find too few rows; iterative scans keep going until LIMIT is met.
    await tx`SET LOCAL hnsw.iterative_scan = relaxed_order`;
    return tx`
      SELECT ${tx.unsafe(COLUMNS)}, 1 - (c.embedding <=> ${vec}::vector) AS score
      FROM chunks c JOIN documents d USING (opportunity_id)
      WHERE c.chunk_set = ${chunkSet} ${filterSql(tx, f)}
      ORDER BY c.embedding <=> ${vec}::vector
      LIMIT ${k}`;
  }) as unknown as Promise<Hit[]>;
}

export async function keywordSearch(sql: postgres.Sql, query: string, chunkSet: string, k: number, f: Filters) {
  // Any query word may match (OR), ranked by ts_rank_cd; title (A) > section (B) > text (C).
  return sql`
    WITH terms AS (
      SELECT string_agg(quote_literal(lexeme), ' | ') AS q
      FROM unnest(tsvector_to_array(to_tsvector('english', ${query}))) AS lexeme
    ), tsq AS (
      SELECT to_tsquery('english', q) AS q FROM terms WHERE q IS NOT NULL
    )
    SELECT ${sql.unsafe(COLUMNS)}, ts_rank_cd(c.tsv, tsq.q, 1)::float8 AS score
    FROM chunks c JOIN documents d USING (opportunity_id), tsq
    WHERE c.chunk_set = ${chunkSet} AND c.tsv @@ tsq.q ${filterSql(sql, f)}
    ORDER BY score DESC
    LIMIT ${k}` as unknown as Promise<Hit[]>;
}

export function rrfFuse(lists: Hit[][], k: number): Hit[] {
  const scores = new Map<string, number>();
  const rows = new Map<string, Hit>();
  for (const list of lists) {
    list.forEach((row, i) => {
      scores.set(row.chunk_id, (scores.get(row.chunk_id) ?? 0) + 1 / (RRF_K + i + 1));
      if (!rows.has(row.chunk_id)) rows.set(row.chunk_id, row);
    });
  }
  return [...scores.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, k)
    .map(([id, score]) => ({ ...rows.get(id)!, score }));
}

export async function hybridSearch(sql: postgres.Sql, ai: Ai, query: string, chunkSet: string, k: number, f: Filters) {
  const [vector, keyword] = await Promise.all([
    vectorSearch(sql, ai, query, chunkSet, CANDIDATES, f),
    keywordSearch(sql, query, chunkSet, CANDIDATES, f),
  ]);
  return rrfFuse([vector, keyword], k);
}

export async function rerank(ai: Ai, query: string, candidates: Hit[], k: number): Promise<Hit[]> {
  if (!candidates.length) return [];
  // Same context the local reranker saw: grant title, section heading, then the text.
  const contexts = candidates.map((c) => ({ text: `${c.title}\n${c.section ?? ""}\n\n${c.text}` }));
  // workers-types omits `query` from this model's input type, although the API requires it.
  const run = ai.run.bind(ai) as unknown as (model: string, inputs: unknown) => Promise<unknown>;
  const out = (await run(RERANKER_MODEL, { query, contexts, top_k: candidates.length })) as {
    response: { id: number; score: number }[];
  };
  // Workers AI already returns 0-1 relevance scores, identical to the local CrossEncoder's
  // sigmoid output (checked on real queries: max difference 0.0000), so no conversion.
  return out.response
    .map((r) => ({ ...candidates[r.id], score: r.score }))
    .sort((a, b) => b.score - a.score)
    .slice(0, k);
}

export async function search(
  sql: postgres.Sql, ai: Ai, query: string, opts: { chunkSet?: string; k?: number; filters?: Filters; method?: Method } = {},
): Promise<Hit[]> {
  const { chunkSet = "section_300", k = 5, filters = {}, method = "hybrid_rerank" } = opts;
  switch (method) {
    case "vector":
      return vectorSearch(sql, ai, query, chunkSet, k, filters);
    case "keyword":
      return keywordSearch(sql, query, chunkSet, k, filters);
    case "hybrid":
      return hybridSearch(sql, ai, query, chunkSet, k, filters);
    case "vector_rerank":
      return rerank(ai, query, await vectorSearch(sql, ai, query, chunkSet, Math.max(k, RERANK_CANDIDATES), filters), k);
    case "hybrid_rerank":
      return rerank(ai, query, await hybridSearch(sql, ai, query, chunkSet, Math.max(k, RERANK_CANDIDATES), filters), k);
  }
}
