from app.answer import format_passages, is_non_answer, verify

PASSAGES = [
    {"opportunity_id": 1, "title": "Wolf Livestock Loss", "section": "ELIGIBILITY > Cost Sharing Required?",
     "page_start": 5, "text": "Yes. The minimum non-Federal cost share is 50 percent of the total project cost."},
    {"opportunity_id": 2, "title": "Tribal Wildlife Grants", "section": None,
     "page_start": 3, "text": "Expected Number of Awards: 80 Award Ceiling: $200,000"},
]


def test_exact_quote_is_verified():
    c = verify({"passage": 1, "quote": "minimum non-Federal cost share is 50 percent"}, PASSAGES)
    assert c.verified and c.title == "Wolf Livestock Loss"


def test_quote_survives_punctuation_and_case_differences():
    assert verify({"passage": 2, "quote": "expected number of awards 80"}, PASSAGES).verified


def test_made_up_or_altered_quote_is_rejected():
    assert not verify({"passage": 1, "quote": "the minimum cost share is 25 percent"}, PASSAGES).verified


def test_quote_from_the_wrong_passage_is_rejected():
    # True text, but it is in passage 2, not passage 1.
    assert not verify({"passage": 1, "quote": "Expected Number of Awards: 80"}, PASSAGES).verified


def test_bad_passage_numbers_and_tiny_quotes_are_rejected():
    assert not verify({"passage": 7, "quote": "Expected Number of Awards: 80"}, PASSAGES).verified
    assert not verify({"passage": "x", "quote": "Expected Number of Awards"}, PASSAGES).verified
    assert not verify({"passage": 2, "quote": "80"}, PASSAGES).verified  # too short to prove anything


def test_passages_are_numbered_with_grant_and_section():
    text = format_passages(PASSAGES)
    assert text.startswith("[1] Grant: Wolf Livestock Loss | Section: ELIGIBILITY")
    assert "[2] Grant: Tribal Wildlife Grants\n" in text


def test_non_answers_are_detected():
    for text in ["There is no specific award ceiling mentioned in the passages.",
                 "The answer is not provided in the passages.",
                 "There is no mention of pre-application due time in the provided passages.",
                 "The documents do not specify the deadline."]:
        assert is_non_answer(text), text


def test_real_answers_are_not_mistaken_for_non_answers():
    for text in ["No, for-profit hospitals are not eligible to apply.",
                 "Cost sharing is not required for this program.",
                 "Individuals are not eligible applicants; schools apply on behalf of students.",
                 "Indirect costs are not allowed under this NOFO."]:
        assert not is_non_answer(text), text
