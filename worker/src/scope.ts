// Scope a question to the agency, grant or program it names, ported 1:1 from app/scope.py.
// Fixes "right fact, wrong grant" answers and refuses programs we don't have; see the Python module.

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
  missing_program: string | null;
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

// Acronyms also safe to recognize in lowercase ("usda", "nih"); doe, dot, dol, dod left out on purpose.
const LOWERCASE_ACRONYMS: Record<string, string[]> = {
  "EPA": ["epa"], "USDA (NIFA)": ["usda", "nifa"], "NEH": ["neh"], "HRSA (HHS)": ["hrsa", "hhs"],
  "State Department (DRL)": ["drl"], "U.S. Fish and Wildlife Service": ["fws", "usfws"],
  "National Institutes of Health (NIH)": ["nih"], "National Science Foundation (NSF)": ["nsf"],
  "NASA": ["nasa"], "NOAA": ["noaa"], "CDC": ["cdc"], "SAMHSA": ["samhsa"], "HUD": ["hud"],
  "Department of Justice": ["doj"], "Department of Homeland Security / FEMA": ["fema", "dhs"],
  "Department of Defense": ["cdmrp", "darpa"], "Small Business Administration": ["sba"],
  "National Endowment for the Arts": ["nea"], "Institute of Museum and Library Services": ["imls"],
  "NIST": ["nist"], "USAID": ["usaid"], "AmeriCorps": ["americorps"], "Department of Energy": ["arpa-e"],
};
const escapeRe = (x: string) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function agencyPatterns(a: Agency): [string, string][] {
  return [
    ...a.patterns.map((p): [string, string] => [p, p.startsWith("\\b") ? "" : "i"]),
    ...(LOWERCASE_ACRONYMS[a.name] ?? []).map((x): [string, string] => ["\\b" + escapeRe(x) + "\\b", ""]),
  ];
}

export function mentionedAgencies(question: string): Agency[] {
  return AGENCIES.filter((a) => agencyPatterns(a).some(([p, f]) => new RegExp(p, f).test(question)));
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
  const scope: Scope = { agencies: agencies.map((a) => a.name), agency_codes: codes, opportunity_ids: [], refusal: null,
    missing_program: null };
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
  if (scope.opportunity_ids.length) return scope;

  const candidates: [string, typeof programKnown][] = [
    ...programNames(question).map((n): [string, typeof programKnown] => [n, programKnown]),
    ...lowercaseProgramNames(question).map((n): [string, typeof programKnown] => [n, lowercaseProgramKnown]),
  ];
  for (const [name, known] of candidates) {
    if (await known(sql, name, titles)) continue;
    scope.missing_program = name;
    if (codes.length) {
      const ours = [...new Set([...titles.values()].map(cleanTitle))].sort();
      const listed = ours.slice(0, 8).join("; ") + (ours.length > 8 ? `; and ${ours.length - 8} more` : "");
      scope.refusal = `I don't have the grant announcement for "${name}". ` +
        `The ${scope.agencies.join(" / ")} announcements I have are: ${listed}.`;
    } else {
      const corpus = AGENCIES.filter((a) => a.codes.length).map((a) => a.name).join(", ");
      scope.refusal = `I couldn't find "${name}" in any of the 200 grant announcements I have (from ${corpus}).`;
    }
    break;
  }
  return scope;
}

const PROGRAM_HEADS = new Set(["program", "programs", "grant", "grants", "award", "awards", "stipend", "stipends",
  "fellowship", "fellowships", "scholarship", "scholarships", "initiative", "fund", "prize", "challenge",
  "competition", "loan", "loans"]);
const HEAD_STEMS = new Set([...PROGRAM_HEADS].map((h) => h.replace(/s+$/, "")));
const CONNECTORS = new Set(["of", "and", "for", "the", "on", "to", "in", "&"]);
const QUESTION_WORDS = new Set(["what", "how", "when", "who", "which", "where", "why", "is", "are", "can", "does",
  "do", "did", "will", "should", "could", "would", "may", "must", "has", "have", "tell", "list"]);
const isUpper = (c: string) => c !== c.toLowerCase() && c === c.toUpperCase();
const isDigit = (c: string) => c >= "0" && c <= "9";
const bare = (w: string) => w.toLowerCase().replace(/[.?!,]+$/, "");

function stripAgencies(name: string): string {
  for (const a of AGENCIES) {
    for (const [p, f] of agencyPatterns(a)) {
      name = name.replace(new RegExp(p + "(['’]s)?", f + "g"), " ");
    }
  }
  const words = name.split(/\s+/).filter(Boolean);
  while (words.length && (CONNECTORS.has(words[0].toLowerCase()) || ["u.s.", "us", "'s", "’s"].includes(words[0].toLowerCase()))) words.shift();
  while (words.length && CONNECTORS.has(words[words.length - 1].toLowerCase())) words.pop();
  return words.join(" ");
}

/** Program names written in the question, as typed, e.g. "NEH Summer Stipends" -> "Summer Stipends". */
export function programNames(question: string): string[] {
  const found = [...question.matchAll(/[A-Za-z0-9][A-Za-z0-9'’&./\-]*/g)];
  const words = found.map((m) => m[0]);
  const names: string[] = [];
  let i = 0;
  while (i < words.length) {
    const w = words[i];
    if (!isUpper(w[0]) || (i === 0 && QUESTION_WORDS.has(w.toLowerCase()))) { i++; continue; }
    let j = i + 1;
    while (j < words.length) {
      if (isUpper(words[j][0]) || isDigit(words[j][0])) { j++; continue; }
      let k = j; // connectors inside a name, possibly several
      while (k < words.length && CONNECTORS.has(words[k].toLowerCase())) k++;
      if (k > j && k < words.length && isUpper(words[k][0])) j = k + 1;
      else break;
    }
    const run = words.slice(i, j);
    const follower = j < words.length ? bare(words[j]) : "";
    if (run.some((x) => PROGRAM_HEADS.has(bare(x))) || PROGRAM_HEADS.has(follower)) {
      const start = found[i].index!;
      const end = found[j - 1].index! + found[j - 1][0].length;
      const name = stripAgencies(question.slice(start, end).replace(/[.?!,]+$/, ""));
      const content = name.toLowerCase().split(/\s+/).filter((x) => x && !CONNECTORS.has(x) && !HEAD_STEMS.has(x.replace(/s+$/, "")));
      if (content.length) names.push(name);
    }
    i = j;
  }
  return names;
}

const LOWERCASE_CONNECTORS = new Set(["and", "of"]);
const LOWERCASE_STOP = new Set([...QUESTION_WORDS, "the", "a", "an", "my", "our", "your", "their", "its", "this",
  "that", "these", "those", "any", "some", "much", "many", "more", "most", "max", "maximum", "minimum", "total", "from",
  "under", "in", "on", "to", "with", "about", "by", "per", "or", "i", "we", "you", "they", "it", "get", "apply", "there",
  "if", "s", "for", "of", "and"]);
const ATTRIBUTE_NOUNS = new Set(["amount", "amounts", "ceiling", "ceilings", "floor", "size", "sizes", "range",
  "deadline", "deadlines", "date", "dates", "funding", "money", "period", "limit", "limits", "cap", "rules",
  "requirements", "requirement", "eligibility", "application", "applications", "recipients", "recipient", "budget",
  "budgets", "terms", "duration", "length", "number", "total"]);
const NEAR_WINDOW_EXTRA = 3;

/** Lowercase program names: the descriptive words before a program word ("nurse corps scholarships"). */
export function lowercaseProgramNames(question: string): string[] {
  const words = question.match(/[a-z0-9][a-z0-9'’\-]*|[A-Z][A-Za-z0-9'’\-]*/g) ?? [];
  const agencyWords = new Set(Object.values(LOWERCASE_ACRONYMS).flat());
  const isLower = (c: string) => c !== c.toUpperCase();
  const names: string[] = [];
  words.forEach((w, i) => {
    if (!PROGRAM_HEADS.has(w.toLowerCase()) || i === 0) return;
    if (i + 1 < words.length && ATTRIBUTE_NOUNS.has(words[i + 1].toLowerCase())) return;
    let j = i;
    while (j > 0) {
      const prev = words[j - 1];
      if (isUpper(prev[0]) || agencyWords.has(prev.toLowerCase())) break;
      if (LOWERCASE_CONNECTORS.has(prev.toLowerCase()) && j - 2 >= 0 && !LOWERCASE_STOP.has(words[j - 2].toLowerCase())
          && isLower(words[j - 2][0]) && !agencyWords.has(words[j - 2].toLowerCase())) { j--; continue; }
      if (LOWERCASE_STOP.has(prev.toLowerCase()) || PROGRAM_HEADS.has(prev.toLowerCase())) break;
      j--;
    }
    const phrase = words.slice(j, i).filter((x, k) => k !== 0 || !CONNECTORS.has(x.toLowerCase()));
    const content = phrase.filter((x) => !CONNECTORS.has(x.toLowerCase()));
    if (content.length >= 2) names.push(phrase.join(" "));
  });
  return names;
}

/** `words` appear in order within some stretch of `window` tokens of `text`. */
export function nearInOrder(words: string[], text: string[], window: number): boolean {
  for (let start = 0; start < text.length; start++) {
    if (text[start] !== words[0]) continue;
    let k = 1;
    for (const t of text.slice(start + 1, start + window)) if (k < words.length && t === words[k]) k++;
    if (k === words.length) return true;
  }
  return false;
}

async function lowercaseProgramKnown(sql: postgres.Sql, name: string, titles: Map<number, string>): Promise<boolean> {
  if (programMatchesTitle(name, titles)) return true;
  const words = tokens(name);
  const ids = [...titles.keys()].join(",");
  const rows = await sql`
    SELECT d.title || ' ' || coalesce(c.section, '') || ' ' || c.text AS t
    FROM chunks c JOIN documents d USING (opportunity_id)
    WHERE c.chunk_set = 'section_300' AND c.opportunity_id = ANY(string_to_array(${ids}, ',')::bigint[])
      AND c.tsv @@ plainto_tsquery('english', ${words.join(" ")})
    LIMIT 200`;
  return rows.some((r) => nearInOrder(words, tokens(r.t as string), words.length + NEAR_WINDOW_EXTRA));
}

/** The name contains one of our titles, or is a shortened form of one (all its words in order). */
export function programMatchesTitle(name: string, titles: Map<number, string>): boolean {
  const nameTokens = tokens(name);
  for (const title of titles.values()) {
    const full = tokens(title);
    const t = [...new Set(full)];
    if (t.length >= 2 && inOrderMatches(t, nameTokens) === t.length) return true;
    if (nameTokens.length >= 2 && inOrderMatches(nameTokens, full) === nameTokens.length) return true;
  }
  return false;
}

async function programKnown(sql: postgres.Sql, name: string, titles: Map<number, string>): Promise<boolean> {
  if (programMatchesTitle(name, titles)) return true;
  const ids = [...titles.keys()].join(",");
  const [row] = await sql`
    SELECT EXISTS (
      SELECT 1 FROM chunks c
      WHERE c.chunk_set = 'section_300' AND c.opportunity_id = ANY(string_to_array(${ids}, ',')::bigint[])
        AND c.tsv @@ phraseto_tsquery('english', ${name})) AS known`;
  return Boolean(row.known);
}

function cleanTitle(title: string): string {
  return title.replace(OPPORTUNITY_CODE, " ")
    .replace(/\b(FY|Fiscal Year)\s*\d{2,4}\b|_NOFO|\bNotice of Funding Opportunity\b/g, " ")
    .replace(/[\s_:\-–]+/g, " ").trim().replace(/^[-–:_ ]+|[-–:_ ]+$/g, "");
}
