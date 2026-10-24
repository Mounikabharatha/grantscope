from app.search import rrf_fuse


def rows(*ids):
    return [{"chunk_id": i, "text": i} for i in ids]


def test_rrf_rewards_chunks_found_by_both_searches():
    vector = rows("a", "b", "c")
    keyword = rows("c", "d")
    fused = [r["chunk_id"] for r in rrf_fuse([vector, keyword], k=4)]
    # "c" is 3rd and 1st -> beats "a", which only one search found (at rank 1).
    assert fused[0] == "c"
    assert set(fused) == {"a", "b", "c", "d"}


def test_rrf_respects_k_and_reports_score():
    fused = rrf_fuse([rows("a", "b", "c")], k=2)
    assert [r["chunk_id"] for r in fused] == ["a", "b"]
    assert abs(fused[0]["score"] - 1 / 61) < 1e-12
