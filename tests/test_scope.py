from app.scope import mentioned_agencies, named_grants, program_matches_title, program_names, tokens


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


def test_program_names_need_a_program_word_and_drop_the_agency():
    assert program_names("What does the NEH Coastal Poetry Stipends program pay?") == ["Coastal Poetry Stipends"]
    assert program_names("How much does the USDA Widget Program award?") == ["Widget Program"]
    assert program_names("What is the maximum award for the USDA FooBar program?") == ["FooBar"]
    # Capitalized names without a program word are not programs.
    assert program_names("Can the University of Arizona apply?") == []
    assert program_names("Can organizations in American Samoa apply?") == []
    # Lowercase names are not detected (a known limit).
    assert program_names("how much do widget grants pay?") == []


def test_program_names_keep_connectors_and_original_spelling():
    assert program_names("How much do EPA Talks on the History of Rivers grants give?") == ["Talks on the History of Rivers"]
    assert program_names("Who is eligible for the USDA SBIR/STTR Phase II program?") == ["SBIR/STTR Phase II"]
    assert program_names("What is the deadline for the EPA's Clean Widget Program?") == ["Clean Widget Program"]


def test_program_matches_title_both_ways():
    titles = {1: "Media Projects", 2: "The Widget Incentive Program Produce Prescription Program"}
    assert program_matches_title("Media Projects Development", titles)  # contains a whole title
    assert program_matches_title("Widget Produce Prescription Program", titles)  # shortened title
    assert not program_matches_title("Summer Stipends", titles)


def test_lowercase_safe_acronyms_are_agencies_but_ordinary_words_are_not():
    assert names("how much does usda give?") == ["USDA (NIFA)"]
    assert names("when are nih awards due?") == ["National Institutes of Health (NIH)"]
    assert names("a doe crossed the dot on the road") == []


def test_lowercase_program_names():
    from app.scope import lowercase_program_names as lp
    assert lp("how much do widget corps scholarships pay?") == ["widget corps"]
    assert lp("what does the usda river basin grant program cover?") == ["river basin"]
    assert lp("what does the river education and training program pay?") == ["river education and training"]
    # Too generic (one descriptive word) or a modifier ("award amounts"): not a program name.
    assert lp("how much are the planning grants?") == []
    assert lp("what is the range of individual award amounts?") == []
    # "for" ends a lowercase name; it joins clauses too often.
    assert lp("which program gives schools money for scholarships?") == []


def test_near_in_order():
    from app.scope import near_in_order
    text = "the nurse education practice quality and retention program".split()
    assert near_in_order(["nurse", "education"], text, 5)
    assert near_in_order(["nurse", "quality"], text, 5)  # a couple of words in between is fine
    assert not near_in_order(["quality", "nurse"], text, 5)  # order matters
    assert not near_in_order(["nurse", "program"], text, 4)  # too far apart
