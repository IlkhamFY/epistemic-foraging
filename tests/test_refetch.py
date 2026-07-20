"""audit --refetch: upstream re-resolution findings. Fully offline."""
import pytest

from foragekit import Workspace
from foragekit.connectors import SourceRecord


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(url):
        raise AssertionError(f"network call attempted: {url}")
    monkeypatch.setattr("foragekit.connectors._get", boom)


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path)
    rec = SourceRecord(title="Spacing Effects in Learning", connector="openalex",
                       openalex_id="W123", authors=["Ada Lovelace"], year=2020,
                       abstract="Spaced practice reliably beats massed practice.")
    sid, _ = w._upsert(rec, patch="test")
    w.store.db.commit()
    w.pin(sid, quote="Spaced practice reliably beats massed practice", locator="abstract")
    return w


def test_refetch_clean_when_upstream_unchanged(ws, monkeypatch):
    monkeypatch.setattr(Workspace, "_refetch_source_text",
                        lambda self, src: "spaced practice reliably beats massed practice.")
    result = ws.audit(refetch=True)
    kinds = {f["kind"] for f in result["findings"]}
    assert "upstream-drift" not in kinds
    assert "refetch-unavailable" not in kinds


def test_refetch_flags_upstream_drift(ws, monkeypatch):
    monkeypatch.setattr(Workspace, "_refetch_source_text",
                        lambda self, src: "this abstract was rewritten upstream entirely.")
    result = ws.audit(refetch=True)
    drift = [f for f in result["findings"] if f["kind"] == "upstream-drift"]
    assert len(drift) == 1
    assert result["counts"]["upstream-drift"] == 1
    assert not result["ok"]


def test_refetch_flags_unavailable_upstream(ws, monkeypatch):
    monkeypatch.setattr(Workspace, "_refetch_source_text", lambda self, src: None)
    result = ws.audit(refetch=True)
    assert result["counts"].get("refetch-unavailable") == 1


def test_audit_without_refetch_never_touches_upstream(ws, monkeypatch):
    def boom(self, src):
        raise AssertionError("refetch ran without being requested")
    monkeypatch.setattr(Workspace, "_refetch_source_text", boom)
    ws.audit()  # must not raise
