import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "evaluate_retrieval", Path(__file__).resolve().parent.parent / "scripts" / "evaluate_retrieval.py")
evaluate_retrieval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluate_retrieval)

RESULTS = [
    {"name": "section_300/vector", "method": "vector", "recall": {5: 0.82}},
    {"name": "section_300/hybrid_rerank", "method": "hybrid_rerank", "recall": {5: 0.85}},
]


def test_gate_passes_when_recall_meets_minimum():
    assert evaluate_retrieval.check_gates(RESULTS, ["vector=0.80"]) == []


def test_gate_fails_when_recall_drops_below_minimum():
    failures = evaluate_retrieval.check_gates(RESULTS, ["vector=0.80", "hybrid_rerank=0.87"])
    assert len(failures) == 1 and "hybrid_rerank" in failures[0]
