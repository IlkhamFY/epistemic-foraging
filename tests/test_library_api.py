"""Library-mode API: score_passages + verify_quote (offline, no workspace)."""
import subprocess
import sys

import pytest

from foragekit import Span, score_passages, verify_quote


def test_score_passages_ranks_on_topic_higher():
    q = "does retrieval augmentation reduce hallucination"
    passages = [
        "retrieval augmentation reduces hallucination in chatbots",
        "grassland grazing mammals and seasonal grasses",
    ]
    scores = score_passages(q, passages)
    assert len(scores) == 2
    assert scores[0] == 1.0          # batch max normalizes to 1.0
    assert scores[1] < scores[0]
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_score_passages_empty_and_offtopic():
    assert score_passages("anything", []) == []
    scores = score_passages("quantum chromodynamics", ["cooking pasta al dente"])
    assert scores == [0.0]


def test_verify_quote_exact_and_canonicalized():
    text = "Retrieval augmentation substantially reduces knowledge hallucination."
    span = verify_quote("substantially reduces knowledge hallucination", text)
    assert isinstance(span, Span)
    assert span.score == 1.0
    # curly quotes / ligature text still verifies (canonicalization)
    span2 = verify_quote("reduces knowledge hallucination", "Retrieval ﬁnding: “reduces knowledge hallucination”")
    assert span2 is not None


def test_verify_quote_fuzzy_and_fail():
    text = "Cold water immersion lowers perceived muscle soreness after training."
    fuzzy = verify_quote("cold water immersion reduces perceived soreness", text)
    assert fuzzy is not None and fuzzy.score < 1.0
    assert verify_quote("creatine improves cognition", text) is None


def test_rag_reviewer_example_runs_offline():
    out = subprocess.run(
        [sys.executable, "examples/rag_reviewer.py"],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0
    assert "pass" in out.stdout and "fail" in out.stdout
    assert "receipt" in out.stdout
