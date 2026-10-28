"""Scope a question to the agency or grant it names, before searching.

Fixes "right fact, wrong grant" answers: the quote check proves a quote is real, but not that it
comes from the program the user asked about (e.g. a nursing grant's "$750,000 per year" quoted as
the answer to an NIH question, or one NEH "Landmarks" NOFO's amount given for its look-alike).

1. Agency: if the question names a federal agency, search only that agency's grants. If it names
   only agencies we have no grants from, refuse straight away and say which agencies we do have.
2. Named grant: if the question contains (nearly) a whole grant title, in order, search only that grant, or
   the most specific of several matching titles ("Landmarks of American History..." vs
   "Landmarks of History...").
3. Missing program: if no grant title matched but the question names a program (a capitalized phrase
   with a word like Program, Grants, Award, Stipends or Fund in or right after it, e.g. "NEH Summer
   Stipends", or in lowercase the descriptive words before such a word, e.g. "nurse corps
   scholarships") that our documents don't mention, refuse and list the programs we do have. Without
   this, the agency filter keeps the agency's other grants and the model quotes one of them instead.
   Safe agency acronyms are also recognized in lowercase ("usda", "nih").

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
    refusal: str | None = None  # set when we can tell up front that the documents can't answer
    missing_program: str | None = None  # a program the question names that our documents don't cover


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


# Acronyms that are also safe to recognize when typed in lowercase ("usda", "nih"). Left out on
# purpose: doe, dot, dol, dod (ordinary words or too ambiguous in lowercase).
LOWERCASE_ACRONYMS = {
    "EPA": ["epa"], "USDA (NIFA)": ["usda", "nifa"], "NEH": ["neh"], "HRSA (HHS)": ["hrsa", "hhs"],
    "State Department (DRL)": ["drl"], "U.S. Fish and Wildlife Service": ["fws", "usfws"],
    "National Institutes of Health (NIH)": ["nih"], "National Science Foundation (NSF)": ["nsf"],
    "NASA": ["nasa"], "NOAA": ["noaa"], "CDC": ["cdc"], "SAMHSA": ["samhsa"], "HUD": ["hud"],
    "Department of Justice": ["doj"], "Department of Homeland Security / FEMA": ["fema", "dhs"],
    "Department of Defense": ["cdmrp", "darpa"], "Small Business Administration": ["sba"],
    "National Endowment for the Arts": ["nea"], "Institute of Museum and Library Services": ["imls"],
    "NIST": ["nist"], "USAID": ["usaid"], "AmeriCorps": ["americorps"], "Department of Energy": ["arpa-e"],
}


def _agency_patterns(agency: Agency):
    """(regex, flags) pairs: acronyms case-sensitive, spelled-out names any case, plus the
    lowercase forms of safe acronyms."""
    for pattern in agency.patterns:
        yield pattern, 0 if pattern.startswith(r"\b") else re.I
    for acronym in LOWERCASE_ACRONYMS.get(agency.name, []):
        yield r"\b" + re.escape(acronym) + r"\b", 0


def mentioned_agencies(question: str) -> list[Agency]:
    found = []
    for agency in AGENCIES:
        if any(re.search(p, question, flags) for p, flags in _agency_patterns(agency)):
            found.append(agency)
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


PROGRAM_HEADS = {"program", "programs", "grant", "grants", "award", "awards", "stipend", "stipends",
                 "fellowship", "fellowships", "scholarship", "scholarships", "initiative", "fund", "prize",
                 "challenge", "competition", "loan", "loans"}
CONNECTORS = {"of", "and", "for", "the", "on", "to", "in", "&"}
# Capitalized only because they start the question.
QUESTION_WORDS = {"what", "how", "when", "who", "which", "where", "why", "is", "are", "can", "does", "do",
                  "did", "will", "should", "could", "would", "may", "must", "has", "have", "tell", "list"}


def _strip_agencies(name: str) -> str:
    for agency in AGENCIES:
        for pattern, flags in _agency_patterns(agency):
            name = re.sub(pattern + r"(['’]s)?", " ", name, flags=flags)
    words = name.split()
    while words and words[0].lower() in CONNECTORS | {"u.s.", "us", "'s", "’s"}:
        words.pop(0)
    while words and words[-1].lower() in CONNECTORS:
        words.pop()
    return " ".join(words)


def program_names(question: str) -> list[str]:
    """Program names written in the question, e.g. "NEH Summer Stipends" -> "Summer Stipends".

    A name is a run of capitalized words (connectors like "of"/"and" allowed inside) that contains a
    program word (Program, Grants, Award, ...) or is followed by one ("the AgVets program").
    Runs without one, like "University of Arizona" or "American Samoa", are ignored. Names are
    returned exactly as typed ("SBIR/STTR Phase II"), so phrase search tokenizes them like the PDFs.
    """
    found = list(re.finditer(r"[A-Za-z0-9][A-Za-z0-9'’&./\-]*", question))
    words = [m.group(0) for m in found]
    names, i = [], 0
    while i < len(words):
        w = words[i]
        if not w[0].isupper() or (i == 0 and w.lower() in QUESTION_WORDS):
            i += 1
            continue
        j = i + 1
        while j < len(words):
            if words[j][0].isupper() or words[j][0].isdigit():
                j += 1
                continue
            k = j  # connectors inside a name, possibly several ("Dialogues on the Experience of War")
            while k < len(words) and words[k].lower() in CONNECTORS:
                k += 1
            if k > j and k < len(words) and words[k][0].isupper():
                j = k + 1
            else:
                break
        run = words[i:j]
        follower = words[j].lower().rstrip(".?!,") if j < len(words) else ""
        if any(x.lower().rstrip(".?!,") in PROGRAM_HEADS for x in run) or follower in PROGRAM_HEADS:
            name = _strip_agencies(question[found[i].start():found[j - 1].end()].rstrip(".?!,"))
            content = [x for x in name.lower().split() if x not in CONNECTORS and x.rstrip("s") not in
                       {h.rstrip("s") for h in PROGRAM_HEADS}]
            if content:
                names.append(name)
        i = j
    return names


# Words that end a lowercase program name when reading backwards from the program word.
LOWERCASE_STOP = QUESTION_WORDS | {
    "the", "a", "an", "my", "our", "your", "their", "its", "this", "that", "these", "those", "any", "some",
    "much", "many", "more", "most", "max", "maximum", "minimum", "total", "from", "under", "in", "on", "to",
    "with", "about", "by", "per", "or", "i", "we", "you", "they", "it", "get", "apply", "there", "much", "if",
    "s", "for", "of", "and"}


LOWERCASE_CONNECTORS = {"and", "of"}  # "for"/"to"/"in" join clauses too often in lowercase text
# After a program word these mean it is a modifier ("award amounts"), not the end of a name.
ATTRIBUTE_NOUNS = {"amount", "amounts", "ceiling", "ceilings", "floor", "size", "sizes", "range", "deadline",
                   "deadlines", "date", "dates", "funding", "money", "period", "limit", "limits", "cap", "rules",
                   "requirements", "requirement", "eligibility", "application", "applications", "recipients",
                   "recipient", "budget", "budgets", "terms", "duration", "length", "number", "total"}


def lowercase_program_names(question: str) -> list[str]:
    """Lowercase program names: the descriptive words just before a program word, e.g.
    "how much do nurse corps scholarships pay?" -> "nurse corps" (agency acronyms dropped,
    connectors like "and" kept inside: "education and training program" -> "education and
    training"). Needs at least two descriptive words; "the planning grants" is too generic."""
    words = re.findall(r"[a-z0-9][a-z0-9'’\-]*|[A-Z][A-Za-z0-9'’\-]*", question)
    agency_words = {a for forms in LOWERCASE_ACRONYMS.values() for a in forms}
    names = []
    for i, w in enumerate(words):
        if w.lower() not in PROGRAM_HEADS or i == 0:
            continue
        if i + 1 < len(words) and words[i + 1].lower() in ATTRIBUTE_NOUNS:
            continue  # "award amounts", "grant deadline": the program word describes something else
        j = i
        while j > 0:
            prev = words[j - 1]
            if prev[0].isupper() or prev.lower() in agency_words:
                break
            if prev.lower() in LOWERCASE_CONNECTORS and j - 2 >= 0 and words[j - 2].lower() not in LOWERCASE_STOP \
                    and words[j - 2][0].islower() and words[j - 2].lower() not in agency_words:
                j -= 1  # keep "and"/"of" inside a name when a descriptive word comes before it
                continue
            if prev.lower() in LOWERCASE_STOP or prev.lower() in PROGRAM_HEADS:
                break
            j -= 1
        phrase = [x for x in words[j:i] if x.lower() not in CONNECTORS or x != words[j]]
        content = [x for x in phrase if x.lower() not in CONNECTORS]
        if len(content) >= 2:
            names.append(" ".join(phrase))
    return names


def program_matches_title(name: str, titles: dict[int, str]) -> bool:
    """The name contains one of our grant titles ("Media Projects Development" ⊇ "Media Projects"),
    or is a shortened form of one (all its words appear in order in the title)."""
    name_tokens = tokens(name)
    for title in titles.values():
        full = tokens(title)
        t = list(dict.fromkeys(full))
        if len(t) >= 2 and in_order_matches(t, name_tokens) == len(t):
            return True
        if len(name_tokens) >= 2 and in_order_matches(name_tokens, full) == len(name_tokens):
            return True
    return False


def program_known(conn: psycopg.Connection, name: str, titles: dict[int, str]) -> bool:
    """A program name is known if it matches one of our titles, or appears as a phrase anywhere in
    our documents (e.g. "Clean Vessel Act Grant Program" in the CVA announcement's text)."""
    if program_matches_title(name, titles):
        return True
    row = conn.execute(
        """SELECT EXISTS (
             SELECT 1 FROM chunks c
             WHERE c.chunk_set = 'section_300' AND c.opportunity_id = ANY(%s)
               AND c.tsv @@ phraseto_tsquery('english', %s))""",
        (list(titles), name),
    ).fetchone()
    return bool(row[0])


NEAR_WINDOW_EXTRA = 3  # lowercase names: words must appear in order within len(name) + 3 words


def lowercase_program_known(conn: psycopg.Connection, name: str, titles: dict[int, str]) -> bool:
    """Lowercase names are often loose descriptions, so the check is looser than a phrase match:
    the name's words must appear in order, close together (within len + 3 words), somewhere in our
    documents, or the name must match one of our titles."""
    if program_matches_title(name, titles):
        return True
    words = tokens(name)
    rows = conn.execute(
        """SELECT d.title || ' ' || coalesce(c.section, '') || ' ' || c.text
           FROM chunks c JOIN documents d USING (opportunity_id)
           WHERE c.chunk_set = 'section_300' AND c.opportunity_id = ANY(%s)
             AND c.tsv @@ plainto_tsquery('english', %s)
           LIMIT 200""",
        (list(titles), " ".join(words)),
    ).fetchall()
    return any(near_in_order(words, tokens(text), len(words) + NEAR_WINDOW_EXTRA) for (text,) in rows)


def near_in_order(words: list[str], text: list[str], window: int) -> bool:
    """True if `words` appear in order within some stretch of `window` tokens of `text`."""
    for start, tok in enumerate(text):
        if tok != words[0]:
            continue
        k = 1
        for t in text[start + 1:start + window]:
            if k < len(words) and t == words[k]:
                k += 1
        if k == len(words):
            return True
    return False


def clean_title(title: str) -> str:
    title = OPPORTUNITY_CODE.sub(" ", title)
    title = re.sub(r"\b(FY|Fiscal Year)\s*\d{2,4}\b|_NOFO|\bNotice of Funding Opportunity\b", " ", title)
    return re.sub(r"[\s_:\-–]+", " ", title).strip(" -–:_")


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
    if scope.opportunity_ids:
        return scope

    candidates = [(n, program_known) for n in program_names(question)]
    candidates += [(n, lowercase_program_known) for n in lowercase_program_names(question)]
    for name, known in candidates:
        if not known(conn, name, titles):
            scope.missing_program = name
            if codes:
                agency = " / ".join(scope.agencies)
                ours = sorted({clean_title(t) for t in titles.values()})
                listed = "; ".join(ours[:8]) + (f"; and {len(ours) - 8} more" if len(ours) > 8 else "")
                scope.refusal = (f"I don't have the grant announcement for \"{name}\". "
                                 f"The {agency} announcements I have are: {listed}.")
            else:
                scope.refusal = (f"I couldn't find \"{name}\" in any of the 200 grant announcements I have "
                                 f"(from {corpus_agencies()}).")
            break
    return scope


def scoped_filters(filters, scope: Scope):
    """Combine the user's filters with the question's scope."""
    from dataclasses import replace

    from app.search import Filters

    filters = filters or Filters()
    return replace(filters,
                   agency_codes=scope.agency_codes or filters.agency_codes,
                   opportunity_ids=scope.opportunity_ids or filters.opportunity_ids)
