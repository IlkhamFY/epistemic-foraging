"""Offline tests for the M2 leftovers (Crossref connector, blocked fuzzy
dedup) and the M3 full-text tier (arXiv HTML).

Fully offline: connectors._get is monkeypatched to serve canned bytes per
URL (or raise), mirroring test_foragekit's offline-guard autouse pattern.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.error

import pytest

import foragekit.connectors as connectors
from foragekit import Workspace, canonical
from foragekit.canonical import EXTRACTOR_VERSION
from foragekit.connectors import Crossref, SourceRecord

# ---------------------------------------------------------------------------
# fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Hard-block HTTP by default; tests opt in to canned routes via serve()."""

    def _blocked(url):  # pragma: no cover - only fires on a bug
        raise AssertionError(f"offline test attempted network access: {url}")

    monkeypatch.setattr(connectors, "_get", _blocked)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("FORAGE_ACTOR", "human:tester")
    return Workspace(tmp_path)


def serve(monkeypatch, routes: dict):
    """Fake connectors._get: canned bytes (or a raised exception) per URL
    prefix. Returns the list of URLs requested, for assertions."""
    calls: list[str] = []

    def _fake(url):
        calls.append(url)
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"unexpected URL in offline test: {url}")

    monkeypatch.setattr(connectors, "_get", _fake)
    return calls


ABSTRACT = ("Retrieval augmented generation reduces hallucination rates in "
            "large language models by grounding every answer in cited sources.")


def add_arxiv_source(ws, arxiv_id="2501.01234", abstract=ABSTRACT,
                     title="Grounded Generation at Scale"):
    rec = SourceRecord(title=title, connector="arxiv", arxiv_id=arxiv_id,
                       authors=["Grace Hopper"], year=2025, abstract=abstract)
    sid, is_new = ws._upsert(rec, "test:fixture")
    ws.store.db.commit()
    assert is_new
    return sid


ARXIV_HTML = b"""<!DOCTYPE html>
<html><head><title>Grounded Generation at Scale</title>
<script>var trackingNoise = 1;</script>
<style>.ltx_page_main { margin: 0 }</style></head>
<body>
<nav class="ltx_page_navbar"><a href="#S1">Table of contents junk</a></nav>
<div class="ltx_page_main">
<h1 class="ltx_title">Grounded Generation at Scale</h1>
<section class="ltx_section">
<p class="ltx_p">Retrieval augmented generation reduces hallucination rates in
large language models by grounding every answer in cited sources.</p>
<p class="ltx_p">We evaluate on <math alttext="\\alpha_{n}"><semantics><mi>&#945;</mi>
<annotation encoding="application/x-tex">\\alpha_{noise}</annotation></semantics></math>
three benchmarks and observe consistent gains across model sizes.</p>
</section>
</div>
<footer class="ltx_page_footer">Generated on Tue by LaTeXML</footer>
</body></html>"""


# ---------------------------------------------------------------------------
# 1. M3: arXiv HTML full-text tier
# ---------------------------------------------------------------------------


class TestArxivFullText:
    def test_html_fetch_caches_full_and_pin_verifies_full_text(self, ws, monkeypatch):
        sid = add_arxiv_source(ws)
        calls = serve(monkeypatch, {"https://arxiv.org/html/2501.01234": ARXIV_HTML})

        r = ws.fetch_text(sid)
        assert r["text_status"] == "cached-full"
        assert r["text_chars"] > 0
        assert calls == ["https://arxiv.org/html/2501.01234"]

        row = ws.store.db.execute(
            "SELECT text, text_status, abstract, extractor_version"
            " FROM sources WHERE id=?", (sid,)).fetchone()
        assert row["text_status"] == "cached-full"
        assert row["extractor_version"] == EXTRACTOR_VERSION
        # abstract column untouched by the full-text cache
        assert row["abstract"] == canonical.canonicalize(ABSTRACT)
        # paragraph text kept
        assert "reduces hallucination rates" in row["text"]
        assert "three benchmarks and observe consistent gains" in row["text"]
        # markup noise stripped: script/style/nav/math/footer
        for noise in ("trackingNoise", "ltx_page_main {", "Table of contents junk",
                      "alpha_{noise}", "α", "Generated on Tue by LaTeXML"):
            assert noise not in row["text"]

        # a new pin against the full text now verifies at the full-text tier
        ev = ws.pin(sid, quote="grounding every answer in cited sources")
        assert ev["verification"] == "verified-full-text"

        # a second fetch reports already-cached and makes no network call
        r2 = ws.fetch_text(sid)
        assert r2["text_status"] == "cached-full"
        assert r2["reason"] == "full text already cached"
        assert len(calls) == 1

    def test_404_keeps_abstract_only_with_honest_reason(self, ws, monkeypatch):
        sid = add_arxiv_source(ws, arxiv_id="1706.03762")
        serve(monkeypatch, {"https://arxiv.org/html/1706.03762":
                            urllib.error.HTTPError(
                                "https://arxiv.org/html/1706.03762", 404,
                                "Not Found", None, None)})

        r = ws.fetch_text(sid)
        assert r["text_status"] == "abstract-only"
        assert r["reason"] == "no HTML render upstream"

        row = ws.store.db.execute(
            "SELECT text, text_status, abstract FROM sources WHERE id=?",
            (sid,)).fetchone()
        assert row["text_status"] == "abstract-only"
        assert row["text"] == row["abstract"]  # unchanged: abstract is the cache

        # pins still verify at the abstract tier
        ev = ws.pin(sid, quote="reduces hallucination rates")
        assert ev["verification"] == "verified-abstract"

    def test_404_with_no_abstract_reports_none(self, ws, monkeypatch):
        sid = add_arxiv_source(ws, arxiv_id="1234.56789", abstract=None,
                               title="Ancient Paper Without Anything")
        serve(monkeypatch, {"https://arxiv.org/html/1234.56789":
                            urllib.error.HTTPError(
                                "https://arxiv.org/html/1234.56789", 404,
                                "Not Found", None, None)})
        r = ws.fetch_text(sid)
        assert r["text_status"] == "none"
        assert r["reason"] == "no HTML render upstream"

    def test_no_arxiv_id_stays_abstract_only_without_network(self, ws):
        rec = SourceRecord(title="Journal-only paper", connector="crossref",
                           doi="10.1000/j.001", authors=["Ada Lovelace"],
                           year=2024, abstract=ABSTRACT)
        sid, _ = ws._upsert(rec, "test:fixture")
        ws.store.db.commit()
        r = ws.fetch_text(sid)  # autouse guard would fail on any HTTP attempt
        assert r["text_status"] == "abstract-only"
        assert "no allowlisted full-text host" in r["reason"]

    def test_allowlist_contains_only_named_hosts(self):
        assert connectors.ALLOWED_HOSTS == {
            "api.openalex.org", "export.arxiv.org", "arxiv.org",
            "api.crossref.org"}


# ---------------------------------------------------------------------------
# 2. M2: Crossref connector
# ---------------------------------------------------------------------------


CROSSREF_JSON = json.dumps({"message": {"items": [
    {"title": ["Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"],
     "DOI": "10.5555/RAG.2020",
     "author": [{"given": "Patrick", "family": "Lewis"},
                {"given": "Ethan", "family": "Perez"}],
     "published": {"date-parts": [[2020, 4, 22]]},
     "container-title": ["Advances in Neural Information Processing Systems"],
     "URL": "https://doi.org/10.5555/rag.2020",
     "abstract": ("<jats:title>Abstract</jats:title><jats:p>Large pre-trained "
                  "models store <jats:italic>factual knowledge</jats:italic> "
                  "&amp; retrieve it at inference time.</jats:p>")},
    {"DOI": "10.5555/minimal.item",
     "issued": {"date-parts": [[2019]]}},
]}}).encode()


class TestCrossref:
    def test_search_parses_records_and_strips_jats(self, monkeypatch):
        calls = serve(monkeypatch, {"https://api.crossref.org/works?": CROSSREF_JSON})
        recs = Crossref().search("retrieval augmented generation", limit=5)

        assert len(calls) == 1
        assert "rows=5" in calls[0]
        assert "mailto=" in calls[0]  # polite-pool contact
        assert "retrieval+augmented+generation" in calls[0]

        assert len(recs) == 2
        r = recs[0]
        assert r.connector == "crossref"
        assert r.title == "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
        assert r.doi == "10.5555/rag.2020"  # lowercased
        assert r.authors == ["Patrick Lewis", "Ethan Perez"]
        assert r.year == 2020
        assert r.venue == "Advances in Neural Information Processing Systems"
        # JATS XML stripped to plain text, entities unescaped, heading dropped
        assert r.abstract == ("Large pre-trained models store factual knowledge "
                              "& retrieve it at inference time.")
        assert r.urls == ["https://doi.org/10.5555/rag.2020"]

        minimal = recs[1]
        assert minimal.title == "(untitled)"
        assert minimal.doi == "10.5555/minimal.item"
        assert minimal.authors == []
        assert minimal.year == 2019  # falls back to issued date-parts
        assert minimal.venue is None
        assert minimal.abstract is None

    def test_registered_and_usable_via_workspace_search(self, ws, monkeypatch):
        assert isinstance(connectors.CONNECTORS["crossref"], Crossref)
        serve(monkeypatch, {"https://api.crossref.org/works?": CROSSREF_JSON})
        r = ws.search("retrieval augmented generation", connectors=["crossref"])
        assert r["added"] == 2 and r["merged"] == 0
        rows = ws.list_sources()
        assert {row["connector"] for row in rows} == {"crossref"}


# ---------------------------------------------------------------------------
# 3. M2: blocked fuzzy dedup (preprint <-> published)
# ---------------------------------------------------------------------------


class TestFuzzyDedup:
    def test_preprint_published_merge(self, ws):
        pre = SourceRecord(
            title="Retrieval-Augmented Generation for Large Language Models: A Survey",
            connector="arxiv", arxiv_id="2312.10997",
            authors=["Yunfan Gao", "Yun Xiong"], year=2023)
        pub = SourceRecord(
            title="Retrieval-Augmented Generation for Large Language Models: Survey",
            connector="crossref", doi="10.9999/tkde.2024.001",
            authors=["Yunfan Gao"], year=2024)
        assert pre.dedupe_key() != pub.dedupe_key()  # different exact keys

        sid1, new1 = ws._upsert(pre, "search:a")
        ws.store.db.commit()
        assert new1
        sid2, new2 = ws._upsert(pub, "search:b")
        ws.store.db.commit()
        assert new2 is False and sid2 == sid1  # merged into the preprint row
        n = ws.store.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        assert n == 1

    def test_same_title_different_first_author_not_merged(self, ws):
        a = SourceRecord(
            title="Retrieval-Augmented Generation for Large Language Models: A Survey",
            connector="arxiv", arxiv_id="2312.10997", authors=["Yunfan Gao"])
        b = SourceRecord(
            title="Retrieval-Augmented Generation for Large Language Models: A Survey",
            connector="crossref", doi="10.9999/other.doi",
            authors=["Cleo Different"])
        sid1, new1 = ws._upsert(a, "p")
        ws.store.db.commit()
        sid2, new2 = ws._upsert(b, "p")
        ws.store.db.commit()
        assert new1 and new2 and sid1 != sid2

    def test_different_papers_with_same_block_prefix_not_merged(self, ws):
        # identical first-25-char normalized prefix, same first author,
        # but genuinely different papers (title similarity below threshold)
        a = SourceRecord(
            title="A comprehensive survey of retrieval augmented generation methods",
            connector="crossref", doi="10.1000/a", authors=["Grace Hopper"])
        b = SourceRecord(
            title="A comprehensive survey of retrieval methods for dense passage ranking systems",
            connector="crossref", doi="10.1000/b", authors=["Grace Hopper"])
        na, nb = canonical.norm_title(a.title), canonical.norm_title(b.title)
        assert na[:25] == nb[:25]  # they really share a dedup block

        sid1, new1 = ws._upsert(a, "p")
        ws.store.db.commit()
        sid2, new2 = ws._upsert(b, "p")
        ws.store.db.commit()
        assert new1 and new2 and sid1 != sid2
        n = ws.store.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        assert n == 2

    def test_old_workspace_migrates_norm_title(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORAGE_ACTOR", "human:tester")
        d = tmp_path / ".forage"
        d.mkdir()
        db = sqlite3.connect(d / "forage.db")
        db.execute(
            "CREATE TABLE sources("
            " id TEXT PRIMARY KEY, openalex_id TEXT, doi TEXT, arxiv_id TEXT,"
            " title TEXT, authors TEXT, year INTEGER, venue TEXT, urls TEXT,"
            " connector TEXT, retrieved_at REAL, read_status TEXT DEFAULT 'unread',"
            " text_status TEXT DEFAULT 'none', abstract TEXT, text TEXT,"
            " extractor_version TEXT, patch TEXT)")
        db.execute("INSERT INTO sources(id, title, authors) VALUES(?,?,?)",
                   ("src_old01", "Old Paper: A Survey!", json.dumps(["Ada Lovelace"])))
        db.commit()
        db.close()

        ws = Workspace(tmp_path)  # migration runs on open
        row = ws.store.db.execute(
            "SELECT norm_title FROM sources WHERE id='src_old01'").fetchone()
        assert row["norm_title"] == "oldpaperasurvey"

        # the migrated row now participates in fuzzy dedup
        dup = SourceRecord(title="Old Paper - A Survey", connector="crossref",
                           doi="10.1/old.pub", authors=["Ada Lovelace"])
        sid, is_new = ws._upsert(dup, "p")
        assert is_new is False and sid == "src_old01"
