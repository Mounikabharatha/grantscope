// Scope a question to the agency or grant it names, ported 1:1 from app/scope.py.
// Fixes "right fact, wrong grant" answers; see the Python module for the reasoning.

import type postgres from "postgres";
import { normalize } from "./text.ts";

const TITLE_MATCH_THRESHOLD = 0.75;
const MIN_TITLE_TOKENS = 3;

interface Agency {
  name: string;
  patterns: string[];
  codes: string[]; // agency_code values in the corpus; empty = we have none
}

const AGENCIES: Agency[] = [
  { name: "EPA", patterns: ["\\bEPA\\b", "Environmental Protection Agency"], codes: ["EPA"] },
  { name: "USDA (NIFA)", patterns: ["\\bUSDA\\b", "Department of Agriculture", "\\bNIFA\\b",
    "National Institute of Food and Agriculture"], codes: ["USDA-NIFA"] },
  { name: "NEH", patterns: ["\\bNEH\\b", "National Endowment for the Humanities"], codes: ["NEH"] },
  { name: "HRSA (HHS)", patterns: ["\\bHRSA\\b", "Health Resources and Services Administration", "\\bHHS\\b",
    "Department of Health and Human Services"], codes: ["HHS-HRSA"] },
  { name: "State Department (DRL)", patterns: ["\\bDRL\\b", "State Department", "Department of State",
    "Democracy,? Human Rights,? and Labor"], codes: ["DOS-DRL"] },
  { name: "U.S. Fish and Wildlife Service", patterns: ["\\bU?S?FWS\\b", "Fish (and|&) Wildlife Service",
    "Department of the Interior"], codes: ["DOI-FWS"] },
  { name: "National Institutes of Health (NIH)", patterns: ["\\bNIH\\b", "National Institutes? of Health"], codes: [] },
  { name: "National Science Foundation (NSF)", patterns: ["\\bNSF\\b", "National Science Foundation"], codes: [] },
  { name: "Department of Energy", patterns: ["\\bDOE\\b", "Department of Energy", "\\bARPA-E\\b"], codes: [] },
  { name: "NASA", patterns: ["\\bNASA\\b", "National Aeronautics and Space"], codes: [] },
  { name: "NOAA", patterns: ["\\bNOAA\\b", "National Oceanic and Atmospheric"], codes: [] },
  { name: "Department of Defense", patterns: ["\\bDo[DD]\\b", "Department of Defense", "\\bCDMRP\\b", "\\bDARPA\\b"], codes: [] },
  { name: "CDC", patterns: ["\\bCDC\\b", "Centers for Disease Control"], codes: [] },
  { name: "SAMHSA", patterns: ["\\bSAMHSA\\b", "Substance Abuse and Mental Health Services"], codes: [] },
  { name: "HUD", patterns: ["\\bHUD\\b", "Housing and Urban Development"], codes: [] },
  { name: "Department of Transportation", patterns: ["\\bU?S?DOT\\b", "Department of Transportation"], codes: [] },
  { name: "Department of Justice", patterns: ["\\bDOJ\\b", "Department of Justice", "Bureau of Justice Assistance"], codes: [] },
  { name: "Department of Education", patterns: ["Department of Education"], codes: [] },
  { name: "Department of Labor", patterns: ["\\bDOL\\b", "Department of Labor"], codes: [] },
  { name: "Department of Homeland Security / FEMA", patterns: ["\\bFEMA\\b", "\\bDHS\\b", "Homeland Security"], codes: [] },
  { name: "Small Business Administration", patterns: ["\\bSBA\\b", "Small Business Administration"], codes: [] },
  { name: "National Endowment for the Arts", patterns: ["\\bNEA\\b", "National Endowment for the Arts"], codes: [] },
  { name: "Institute of Museum and Library Services", patterns: ["\\bIMLS\\b", "Institute of Museum and Library"], codes: [] },
  { name: "NIST", patterns: ["\\bNIST\\b", "National Institute of Standards"], codes: [] },
  { name: "USAID", patterns: ["\\bUSAID\\b"], codes: [] },
  { name: "AmeriCorps", patterns: ["\\bAmeriCorps\\b"], codes: [] },
];

const STOPWORDS = new Set(["a", "an", "and", "the", "of", "for", "to", "in", "on", "with", "by", "at", "or", "fy",
  "fiscal", "year", "nofo", "notice", "funding", "opportunity"]);
const OPPORTUNITY_CODE = /\b[A-Z]\d{2}[A-Z]{2}\d{5}\b/g; // e.g. F26AS00088

export interface Scope {
  agencies: string[];
  agency_codes: string[];
  opportunity_ids: number[];
  refusal: string | null;
}

export function tokens(text: string): string[] {
  const out: string[] = [];
  for (const tok of normalize(text.replace(OPPORTUNITY_CODE, " ")).split(" ").filter(Boolean)) {
    for (let part of tok.match(/[a-z]+|\d+/g) ?? []) {
      if (/^\d+$/.test(part)) part = part.replace(/^0+/, "") || "0";
      else if (part.length > 3 && part.endsWith("s") && !part.endsWith("ss")) part = part.slice(0, -1);
      if (!STOPWORDS.has(part)) out.push(part);
    }
  }
  return out;
}

/** Title words appearing in the question in the title's order (longest common subsequence). */
export function inOrderMatches(title: string[], question: string[]): number {
  let prev = new Array(question.length + 1).fill(0);
  for (const t of title) {
    const cur = [0];
    question.forEach((w, j) => cur.push(t === w ? prev[j] + 1 : Math.max(prev[j + 1], cur[j])));
    prev = cur;
  }
  return prev[question.length];
}

export function mentionedAgencies(question: string): Agency[] {
  // Acronyms (patterns starting with \b) match case-sensitively; spelled-out names in any case.
  return AGENCIES.filter((a) =>
    a.patterns.some((p) => new RegExp(p, p.startsWith("\\b") ? "" : "i").test(question)));
}

export function namedGrants(question: string, titles: Map<number, string>): number[] {
  const q = tokens(question);
  const best: [number, number, number][] = [];
  for (const [oid, title] of titles) {
    const t = [...new Set(tokens(title))];
    if (t.length < MIN_TITLE_TOKENS) continue;
    const matched = inOrderMatches(t, q);
    const coverage = matched / t.length;
    if (coverage >= TITLE_MATCH_THRESHOLD) best.push([coverage, matched, oid]);
  }
  if (!best.length) return [];
  const [topC, topM] = best.reduce((a, b) => (b[0] > a[0] || (b[0] === a[0] && b[1] > a[1]) ? b : a));
  return best.filter(([c, m]) => c === topC && m === topM).map(([, , oid]) => oid);
}

// Titles change only when the data is re-migrated; cache them per Worker instance.
let documentsCache: { opportunity_id: number; title: string; agency_code: string }[] | null = null;

async function documents(sql: postgres.Sql) {
  documentsCache ??= (await sql`
    SELECT opportunity_id::int AS opportunity_id, title, agency_code FROM documents`) as unknown as {
    opportunity_id: number; title: string; agency_code: string }[];
  return documentsCache;
}

export async function scopeQuestion(sql: postgres.Sql, question: string): Promise<Scope> {
  const agencies = mentionedAgencies(question);
  const codes = [...new Set(agencies.flatMap((a) => a.codes))].sort();
  const scope: Scope = { agencies: agencies.map((a) => a.name), agency_codes: codes, opportunity_ids: [], refusal: null };
  if (agencies.length && !codes.length) {
    const corpus = AGENCIES.filter((a) => a.codes.length).map((a) => a.name).join(", ");
    scope.refusal = `My documents don't include grants from ${agencies.map((a) => a.name).join(" or ")}. ` +
      `I only have grant announcements from ${corpus}.`;
    return scope;
  }
  const docs = await documents(sql);
  const titles = new Map(docs.filter((d) => !codes.length || codes.includes(d.agency_code))
    .map((d) => [d.opportunity_id, d.title]));
  scope.opportunity_ids = namedGrants(question, titles);
  return scope;
}
