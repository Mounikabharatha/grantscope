from app.evaluation import Question, is_relevant, normalize


def q(evidence, opportunity_id=1):
    return Question("q1", "answerable", "amount", "?", opportunity_id, evidence, "", "keep")


def test_normalize_ignores_punctuation_and_quotes():
    assert normalize("“DERA National NOFO Question.”") == normalize('"DERA National NOFO Question"')
    assert normalize("Award Ceiling:\n$675,000") == "award ceiling 675 000"


def test_relevant_needs_right_grant_and_quote():
    chunk = {"opportunity_id": 1, "section": "Proposal (15 pages maximum)", "text": "Award Ceiling: $675,000"}
    assert is_relevant(chunk, q("award ceiling: $675,000"))
    assert is_relevant(chunk, q("15 pages maximum"))  # quote may sit in the heading
    assert not is_relevant(chunk, q("award ceiling: $675,000", opportunity_id=2))
    assert not is_relevant(chunk, q("$700,000"))


def test_discovery_question_matches_any_chunk_of_grant():
    assert is_relevant({"opportunity_id": 1, "section": None, "text": "anything"}, q(""))
