from app.scope import mentioned_agencies, named_grants, tokens


def names(q):
    return [a.name for a in mentioned_agencies(q)]


def test_acronyms_are_case_sensitive_names_are_not():
    assert names("What does NSF fund?") == ["National Science Foundation (NSF)"]
    assert names("what does the national science foundation fund?") == ["National Science Foundation (NSF)"]
    # Ordinary words that look like acronyms are not agencies.
    assert names("Does the grant cover a doe and her fawn? I'll dot the i's.") == []


def test_state_governments_is_not_the_state_department():
    assert names("Can state governments apply?") == []
    assert names("What does the State Department fund?") == ["State Department (DRL)"]


def test_agency_in_corpus_has_codes_and_others_do_not():
    by_name = {a.name: a for a in mentioned_agencies("Compare EPA and NIH funding")}
    assert by_name["EPA"].codes == ("EPA",)
    assert by_name["National Institutes of Health (NIH)"].codes == ()


def test_tokens_split_digits_drop_codes_and_plurals():
    assert tokens("F26AS00088 FY2025 Region 06 Wetlands Grants") == ["2025", "region", "6", "wetland", "grant"]


TITLES = {
    1: "Coastal Habitat Grants for Small Towns",
    2: "Coastal Habitat Grants for Rural Small Towns",
    3: "River Monitoring Program",
    4: "Habitat",  # too short to count as a named grant
}


def test_named_grant_picks_the_most_specific_full_match():
    assert named_grants("How much do Coastal Habitat Grants for Rural Small Towns provide?", TITLES) == [2]
    assert named_grants("How much do Coastal Habitat Grants for Small Towns provide?", TITLES) == [1]


def test_title_words_must_appear_in_order():
    titles = {5: "Research Facilities Act Program"}
    # All four title words appear, but scattered and out of order: not a mention of that grant.
    assert named_grants("Is an inspection program for boat facilities eligible under the research Act?", titles) == []
    assert named_grants("What does the Research Facilities Act Program fund?", titles) == [5]


def test_no_named_grant_when_title_is_only_partly_mentioned():
    assert named_grants("What habitat grants exist for towns?", TITLES) == []
