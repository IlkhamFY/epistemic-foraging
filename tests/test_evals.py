"""Offline tests for the eval harness metric math (CI-safe, no network)."""
import pytest

from evals import harness
from foragekit import Workspace
from foragekit.connectors import SourceRecord


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(url):
        raise AssertionError(f"network call attempted: {url}")
    monkeypatch.setattr("foragekit.connectors._get", boom)


def _seed_corpus(ws: Workspace):
    recs = [
        SourceRecord(title="Retrieval augmentation reduces hallucination",
                     connector="openalex", openalex_id="W1", doi="10.1/a",
                     authors=["A"], year=2021,
                     abstract="retrieval augmentation reduces hallucination in chatbots"),
        SourceRecord(title="A survey of grassland ecology", connector="openalex",
                     openalex_id="W2", doi="10.1/b", authors=["B"], year=2020,
                     abstract="grassland species diversity and grazing"),
        SourceRecord(title="Hallucination in language models", connector="openalex",
                     openalex_id="W3", doi="10.1/c", authors=["C"], year=2023,
                     abstract="why language models hallucinate facts"),
    ]
    for r in recs:
        ws._upsert(r, patch="fixture")
    ws.store.db.commit()


def test_recall_math(tmp_path):
    ws = Workspace(tmp_path)
    _seed_corpus(ws)
    assert harness.recall(ws, ["W1", "W3", "W999"]) == pytest.approx(2 / 3)
    assert harness.recall(ws, []) == 0.0


def test_ordering_proxy_prefers_relevant_targets(tmp_path):
    ws = Workspace(tmp_path)
    _seed_corpus(ws)
    q = "do retrieval augmented models hallucinate less"
    out = harness.ordering_recall(ws, q, ["W1", "W3"], ks=(1, 2))
    assert out["targets_in_pool"] == 2
    for label in ("frontier", "relevance_only"):
        assert 0.0 <= out[label]["recall@1"] <= 1.0
        assert out[label]["first_target_rank"] is not None
    # the grassland paper must not outrank both on-topic targets
    assert out["relevance_only"]["recall@2"] == 1.0


def test_query_variants_dedupe_and_strip_stopwords():
    v = harness.query_variants("How do large models hallucinate?")
    assert v[0] == "How do large models hallucinate?"
    assert "models hallucinate" in v[1]
    assert len(v) == len(set(v))


def test_budget_zero_makes_no_network_calls(tmp_path):
    ws = Workspace(tmp_path)
    harness.discover_keyword(ws, "anything at all", budget=0)  # must not raise


def test_dataset_validation(tmp_path):
    import json
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"name": "x"}))
    with pytest.raises(ValueError):
        harness.load_dataset(p)
