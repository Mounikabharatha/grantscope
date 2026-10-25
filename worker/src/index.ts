// GrantScope on Cloudflare Workers.
//
//   /, /pdfs/*   static assets (the search page and the grant PDFs), served before this code runs
//   /search      hybrid + reranked passage search (JSON)
//   /ask         cited answer or refusal (JSON)
//   /agencies    agencies + grant counts for the page's filter
//   /health      database + pgvector check
//
// Postgres (Neon) is reached through Hyperdrive, which pools connections near the database;
// embeddings, reranking and answers run on Workers AI with the same models used locally.

import postgres from "postgres";
import { answerQuestion } from "./answer.ts";
import { METHODS, search, type Filters, type Method } from "./search.ts";

export interface Env {
  AI: Ai;
  HYPERDRIVE: Hyperdrive;
  ASSETS: Fetcher;
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

function readFilters(params: URLSearchParams): Filters {
  const minAward = params.get("min_award");
  return {
    agency: params.get("agency") || undefined,
    minAward: minAward ? Number(minAward) : undefined,
    openOn: params.get("open_on") || undefined,
  };
}

function readQuestion(params: URLSearchParams): string | null {
  const q = (params.get("q") ?? "").trim();
  return q.length >= 3 && q.length <= 500 ? q : null;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method !== "GET") return json({ error: "method not allowed" }, 405);

    const sql = postgres(env.HYPERDRIVE.connectionString, { max: 5, fetch_types: false });
    ctx.waitUntil(sql.end()); // close the pooled connection once the response is sent
    try {
      switch (url.pathname) {
        case "/health": {
          const [row] = await sql`
            SELECT (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector_version,
                   (SELECT count(*)::int FROM documents) AS documents`;
          return json({ status: "ok", ...row });
        }
        case "/agencies": {
          const rows = await sql`
            SELECT agency_code AS code, min(agency) AS name, count(*)::int AS grants
            FROM documents GROUP BY 1 ORDER BY 3 DESC`;
          return json(rows);
        }
        case "/search": {
          const q = readQuestion(url.searchParams);
          if (!q) return json({ error: "q must be 3-500 characters" }, 400);
          const method = (url.searchParams.get("method") ?? "hybrid_rerank") as Method;
          if (!METHODS.includes(method)) return json({ error: `method must be one of ${METHODS.join(", ")}` }, 400);
          const k = Math.min(Math.max(Number(url.searchParams.get("k") ?? 5) || 5, 1), 20);
          const start = Date.now();
          const results = await search(sql, env.AI, q, { k, method, filters: readFilters(url.searchParams) });
          return json({ query: q, method, took_ms: Date.now() - start, results });
        }
        case "/ask": {
          const q = readQuestion(url.searchParams);
          if (!q) return json({ error: "q must be 3-500 characters" }, 400);
          const start = Date.now();
          const answer = await answerQuestion(sql, env.AI, q, readFilters(url.searchParams));
          return json({ ...answer, took_ms: Date.now() - start });
        }
        default:
          return env.ASSETS.fetch(request);
      }
    } catch (err) {
      console.error(err);
      return json({ error: "internal error" }, 500);
    }
  },
} satisfies ExportedHandler<Env>;
