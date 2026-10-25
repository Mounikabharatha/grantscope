"""Scope a question to the agency or grant it names, before searching.

Fixes "right fact, wrong grant" answers: the quote check proves a quote is real, but not that it
comes from the program the user asked about (e.g. a nursing grant's "$750,000 per year" quoted as
the answer to an NIH question, or one NEH "Landmarks" NOFO's amount given for its look-alike).

1. Agency: if the question names a federal agency, search only that agency's grants. If it names
   only agencies we have no grants from, refuse straight away and say which agencies we do have.
2. Named grant: if the question contains (nearly) a whole grant title, in order, search only that grant, or
   the most specific of several matching titles ("Landmarks of American History..." vs
   "Landmarks of History...").

The agency list covers major federal funders in general, not just the six in the corpus; the title
threshold (75% of a title's words) was fixed before evaluating. Questions that name neither an
agency nor a grant are searched as before.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

import psycopg

from app.evaluation import normalize

TITLE_MATCH_THRESHOLD = 0.75
MIN_TITLE_TOKENS = 3


@dataclass(frozen=True)
class Agency:
    name: str
    patterns: tuple[str, ...]
    codes: tuple[str, ...] = ()  # agency_code values in our corpus; empty = we have none


AGENCIES = [
    # In the corpus
    Agency("EPA", (r"\bEPA\b", r"Environmental Protection Agency"), ("EPA",)),
    Agency("USDA (NIFA)", (r"\bUSDA\b", r"Department of Agriculture", r"\bNIFA\b",
                           r"National Institute of Food and Agriculture"), ("USDA-NIFA",)),
    Agency("NEH", (r"\bNEH\b", r"National Endowment for the Humanities"), ("NEH",)),
    Agency("HRSA (HHS)", (r"\bHRSA\b", r"Health Resources and Services Administration", r"\bHHS\b",
                          r"Department of Health and Human Services"), ("HHS-HRSA",)),
    Agency("State Department (DRL)", (r"\bDRL\b", r"State Department", r"Department of State",
                                      r"Democracy,? Human Rights,? and Labor"), ("DOS-DRL",)),
    Agency("U.S. Fish and Wildlife Service", (r"\bU?S?FWS\b", r"Fish (and|&) Wildlife Service",
                                              r"Department of the Interior"), ("DOI-FWS",)),
    # Major federal funders that are NOT in the corpus
    Agency("National Institutes of Health (NIH)", (r"\bNIH\b", r"National Institutes? of Health")),
    Agency("National Science Foundation (NSF)", (r"\bNSF\b", r"National Science Foundation")),
    Agency("Department of Energy", (r"\bDOE\b", r"Department of Energy", r"\bARPA-E\b")),
    Agency("NASA", (r"\bNASA\b", r"National Aeronautics and Space")),
    Agency("NOAA", (r"\bNOAA\b", r"National Oceanic and Atmospheric")),
    Agency("Department of Defense", (r"\bDo[DD]\b", r"Department of Defense", r"\bCDMRP\b", r"\bDARPA\b")),
    Agency("CDC", (r"\bCDC\b", r"Centers for Disease Control")),
    Agency("SAMHSA", (r"\bSAMHSA\b", r"Substance Abuse and Mental Health Services")),
    Agency("HUD", (r"\bHUD\b", r"Housing and Urban Development")),
    Agency("Department of Transportation", (r"\bU?S?DOT\b", r"Department of Transportation")),
    Agency("Department of Justice", (r"\bDOJ\b", r"Department of Justice", r"Bureau of Justice Assistance")),
    Agency("Department of Education", (r"Department of Education",)),
    Agency("Department of Labor", (r"\bDOL\b", r"Department of Labor")),
    Agency("Department of Homeland Security / FEMA", (r"\bFEMA\b", r"\bDHS\b", r"Homeland Security")),
    Agency("Small Business Administration", (r"\bSBA\b", r"Small Business Administration")),
    Agency("National Endowment for the Arts", (r"\bNEA\b", r"National Endowment for the Arts")),
    Agency("Institute of Museum and Library Services", (r"\bIMLS\b", r"Institute of Museum and Library")),
    Agency("NIST", (r"\bNIST\b", r"National Institute of Standards")),
    Agency("USAID", (r"\bUSAID\b",)),
    Agency("AmeriCorps", (r"\bAmeriCorps\b",)),
]

STOPWORDS = {"a", "an", "and", "the", "of", "for", "to", "in", "on", "with", "by", "at", "or", "fy",
             "fiscal", "year", "nofo", "notice", "funding", "opportunity"}
OPPORTUNITY_CODE = re.compile(r"\b[A-Z]\d{2}[A-Z]{2}\d{5}\b")  # e.g. F26AS00088


@dataclass
class Scope:
    agencies: list[str] = field(default_factory=list)  # agency names mentioned in the question
    agency_codes: list[str] = field(default_factory=list)  # corpus agency codes to restrict to
    opportunity_ids: list[int] = field(default_factory=list)  # named grant(s) to restrict to
    refusal: str | None = None  # set when the question only names agencies we have no grants from


def tokens(text: str) -> list[str]:
    """Content words in order, with letter/digit runs split ("FY2025" -> fy, 2025), leading zeros
    and a plural 's' dropped ("Region 06" ~ "Region 6", "Wetlands" ~ "Wetland")."""
    text = OPPORTUNITY_CODE.sub(" ", text)
    out = []
    for tok in normalize(text).split():
        for part in re.findall(r"[a-z]+|\d+", tok):
            if part.isdigit():
                part = part.lstrip("0") or "0"
            elif len(part) > 3 and part.endswith("s") and not part.endswith("ss"):
                part = part[:-1]
            if part not in STOPWORDS:
                out.append(part)
    return out


def in_order_matches(title: list[str], question: list[str]) -> int:
    """How many title words appear in the question in the title's order (longest common
    subsequence). Order matters: "Research Facilities Act Program" is not named by a question
    that mentions "program ... facilities ... Act" in passing."""
    prev = [0] * (len(question) + 1)
    for t in title:
        cur = [0]
        for j, w in enumerate(question, 1):
            cur.append(prev[j - 1] + 1 if t == w else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def mentioned_agencies(question: str) -> list[Agency]:
    found = []
    for agency in AGENCIES:
        for pattern in agency.patterns:
            # Acronyms (patterns starting with \b, e.g. \bNSF\b) match case-sensitively so
            # ordinary words like "doe" or "dot" don't count; spelled-out names match in any case.
            flags = 0 if pattern.startswith(r"\b") else re.I
            if re.search(pattern, question, flags):
                found.append(agency)
                break
    return found


def named_grants(question: str, titles: dict[int, str]) -> list[int]:
    """Grants whose title (nearly) appears in the question; the most specific match wins."""
    q = tokens(question)
    best: list[tuple[float, int, int]] = []
    for oid, title in titles.items():
        t = list(dict.fromkeys(tokens(title)))  # drop repeated words, keep order
        if len(t) < MIN_TITLE_TOKENS:
            continue
        matched = in_order_matches(t, q)
        coverage = matched / len(t)
        if coverage >= TITLE_MATCH_THRESHOLD:
            best.append((coverage, matched, oid))
    if not best:
        return []
    top = max((c, m) for c, m, _ in best)
    return [oid for c, m, oid in best if (c, m) == top]


@lru_cache(maxsize=1)
def _documents(dsn: str) -> tuple[tuple[int, str, str], ...]:
    with psycopg.connect(dsn) as conn:
        return tuple(conn.execute("SELECT opportunity_id, title, agency_code FROM documents").fetchall())


def corpus_agencies() -> str:
    return ", ".join(a.name for a in AGENCIES if a.codes)


def scope_question(conn: psycopg.Connection, question: str) -> Scope:
    docs = _documents(conn.info.dsn)
    agencies = mentioned_agencies(question)
    codes = sorted({c for a in agencies for c in a.codes})
    scope = Scope(agencies=[a.name for a in agencies], agency_codes=codes)

    if agencies and not codes:
        names = " or ".join(a.name for a in agencies)
        scope.refusal = (f"My documents don't include grants from {names}. "
                         f"I only have grant announcements from {corpus_agencies()}.")
        return scope

    titles = {oid: title for oid, title, code in docs if not codes or code in codes}
    scope.opportunity_ids = named_grants(question, titles)
    return scope


def scoped_filters(filters, scope: Scope):
    """Combine the user's filters with the question's scope."""
    from dataclasses import replace

    from app.search import Filters

    filters = filters or Filters()
    return replace(filters,
                   agency_codes=scope.agency_codes or filters.agency_codes,
                   opportunity_ids=scope.opportunity_ids or filters.opportunity_ids)
