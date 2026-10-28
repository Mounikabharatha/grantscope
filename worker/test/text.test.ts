// Parity with the Python tests: same inputs must give the same verdicts in the Worker.
import { test } from "node:test";
import assert from "node:assert/strict";
import { isNonAnswer, normalize, parseJson } from "../src/text.ts";
import { formatPassages, verify } from "../src/answer.ts";
import { rrfFuse } from "../src/search.ts";
import { mentionedAgencies, namedGrants, programMatchesTitle, programNames, tokens } from "../src/scope.ts";

const PASSAGES = [
  { chunk_id: "a", opportunity_id: 1, title: "Wolf Livestock Loss", section: "ELIGIBILITY > Cost Sharing Required?",
    page_start: 5, page_end: 5, text: "Yes. The minimum non-Federal cost share is 50 percent of the total project cost.",
    agency_code: "DOI-FWS", award_ceiling: null, close_date: null, source_url: "", score: 1 },
  { chunk_id: "b", opportunity_id: 2, title: "Tribal Wildlife Grants", section: null,
    page_start: 3, page_end: 3, text: "Expected Number of Awards: 80 Award Ceiling: $200,000",
    agency_code: "DOI-FWS", award_ceiling: null, close_date: null, source_url: "", score: 1 },
];

test("normalize matches the Python version", () => {
  assert.equal(normalize("Award Ceiling:\n$675,000"), "award ceiling 675 000");
  assert.equal(normalize("For-proﬁt, diﬀerent"), normalize("For-profit, different"));
  assert.equal(normalize("“DERA National NOFO Question.”"), normalize('"DERA National NOFO Question"'));
});

test("quote verification accepts exact quotes and rejects altered or misattributed ones", () => {
  assert.ok(verify({ passage: 1, quote: "minimum non-Federal cost share is 50 percent" }, PASSAGES).verified);
  assert.ok(verify({ passage: 2, quote: "expected number of awards 80" }, PASSAGES).verified);
  assert.ok(!verify({ passage: 1, quote: "the minimum cost share is 25 percent" }, PASSAGES).verified);
  assert.ok(!verify({ passage: 1, quote: "Expected Number of Awards: 80" }, PASSAGES).verified);
  assert.ok(!verify({ passage: 7, quote: "Expected Number of Awards: 80" }, PASSAGES).verified);
  assert.ok(!verify({ passage: "x", quote: "Expected Number of Awards" }, PASSAGES).verified);
  assert.ok(!verify({ passage: 2, quote: "80" }, PASSAGES).verified);
});

test("non-answers are detected, real answers are not", () => {
  for (const t of ["There is no specific award ceiling mentioned in the passages.",
    "The answer is not provided in the passages.",
    "There is no mention of pre-application due time in the provided passages.",
    "The documents do not specify the deadline."]) assert.ok(isNonAnswer(t), t);
  for (const t of ["No, for-profit hospitals are not eligible to apply.",
    "Cost sharing is not required for this program.",
    "Individuals are not eligible applicants; schools apply on behalf of students.",
    "Indirect costs are not allowed under this NOFO."]) assert.ok(!isNonAnswer(t), t);
});

test("passages are numbered with grant and section", () => {
  const text = formatPassages(PASSAGES);
  assert.ok(text.startsWith("[1] Grant: Wolf Livestock Loss | Section: ELIGIBILITY"));
  assert.ok(text.includes("[2] Grant: Tribal Wildlife Grants\n"));
});

test("RRF rewards chunks found by both searches", () => {
  const rows = (...ids: string[]) => ids.map((id) => ({ ...PASSAGES[0], chunk_id: id }));
  const fused = rrfFuse([rows("a", "b", "c"), rows("c", "d")], 4).map((r) => r.chunk_id);
  assert.equal(fused[0], "c");
  assert.equal(Math.abs(rrfFuse([rows("a")], 1)[0].score - 1 / 61) < 1e-12, true);
});

test("parseJson tolerates text around the object", () => {
  assert.deepEqual(parseJson('Sure! {"answerable": false} hope that helps'), { answerable: false });
  assert.deepEqual(parseJson({ answerable: true }), { answerable: true });
});

// Same cases as tests/test_scope.py
test("agency acronyms are case-sensitive, names are not", () => {
  const names = (q: string) => mentionedAgencies(q).map((a) => a.name);
  assert.deepEqual(names("What does NSF fund?"), ["National Science Foundation (NSF)"]);
  assert.deepEqual(names("what does the national science foundation fund?"), ["National Science Foundation (NSF)"]);
  assert.deepEqual(names("Does the grant cover a doe and her fawn? I'll dot the i's."), []);
  assert.deepEqual(names("Can state governments apply?"), []);
  assert.deepEqual(names("What does the State Department fund?"), ["State Department (DRL)"]);
});

test("tokens split digits, drop codes and plurals", () => {
  assert.deepEqual(tokens("F26AS00088 FY2025 Region 06 Wetlands Grants"), ["2025", "region", "6", "wetland", "grant"]);
});

test("named grant: most specific in-order full match wins", () => {
  const titles = new Map([[1, "Coastal Habitat Grants for Small Towns"], [2, "Coastal Habitat Grants for Rural Small Towns"],
    [3, "River Monitoring Program"], [4, "Habitat"]]);
  assert.deepEqual(namedGrants("How much do Coastal Habitat Grants for Rural Small Towns provide?", titles), [2]);
  assert.deepEqual(namedGrants("How much do Coastal Habitat Grants for Small Towns provide?", titles), [1]);
  assert.deepEqual(namedGrants("What habitat grants exist for towns?", titles), []);
  const rfa = new Map([[5, "Research Facilities Act Program"]]);
  assert.deepEqual(namedGrants("Is an inspection program for boat facilities eligible under the research Act?", rfa), []);
  assert.deepEqual(namedGrants("What does the Research Facilities Act Program fund?", rfa), [5]);
});

// Same cases as tests/test_scope.py (program names)
test("program names need a program word, drop the agency, keep the original spelling", () => {
  assert.deepEqual(programNames("What does the NEH Coastal Poetry Stipends program pay?"), ["Coastal Poetry Stipends"]);
  assert.deepEqual(programNames("How much does the USDA Widget Program award?"), ["Widget Program"]);
  assert.deepEqual(programNames("What is the maximum award for the USDA FooBar program?"), ["FooBar"]);
  assert.deepEqual(programNames("Can the University of Arizona apply?"), []);
  assert.deepEqual(programNames("Can organizations in American Samoa apply?"), []);
  assert.deepEqual(programNames("how much do widget grants pay?"), []);
  assert.deepEqual(programNames("How much do EPA Talks on the History of Rivers grants give?"), ["Talks on the History of Rivers"]);
  assert.deepEqual(programNames("Who is eligible for the USDA SBIR/STTR Phase II program?"), ["SBIR/STTR Phase II"]);
  assert.deepEqual(programNames("What is the deadline for the EPA's Clean Widget Program?"), ["Clean Widget Program"]);
});

test("program matches a title both ways", () => {
  const titles = new Map([[1, "Media Projects"], [2, "The Widget Incentive Program Produce Prescription Program"]]);
  assert.ok(programMatchesTitle("Media Projects Development", titles));
  assert.ok(programMatchesTitle("Widget Produce Prescription Program", titles));
  assert.ok(!programMatchesTitle("Summer Stipends", titles));
});
