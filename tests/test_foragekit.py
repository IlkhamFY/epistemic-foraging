"""Offline test suite for foragekit.

Every test runs against a tmp_path workspace. Sources are inserted either via
Workspace._upsert with a hand-built SourceRecord (no network involved) or via
direct SQL. An autouse fixture hard-blocks the connector HTTP layer so any
accidental network call fails the test immediately.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

import foragekit.connectors as connectors
from foragekit import Workspace, canonical, scoring, synthesis
from foragekit.canonical import EXTRACTOR_VERSION, find_span
from foragekit.connectors import SourceRecord

# ---------------------------------------------------------------------------
# fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Hard-block the only HTTP path in the package for in-process tests."""

    def _blocked(url):  # pragma: no cover - only fires on a bug
        raise AssertionError(f"offline test attempted network access: {url}")

    monkeypatch.setattr(connectors, "_get", _blocked)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("FORAGE_ACTOR", "human:tester")
    return Workspace(tmp_path)


def add_source(ws, title, abstract=None, authors=None, year=2024):
    """Insert a source offline via a hand-built SourceRecord."""
    rec = SourceRecord(
        title=title,
        connector="test",
        authors=authors if authors is not None else ["Ada Lovelace"],
        year=year,
        abstract=abstract,
    )
    sid, is_new = ws._upsert(rec, "test:fixture")
    ws.store.db.commit()
    assert is_new
    return sid


ABSTRACT = (
    "Retrieval augmented generation reduces hallucination rates in large "
    "language models by grounding every answer in cited sources."
)

# ---------------------------------------------------------------------------
# 1. canonicalize
# ---------------------------------------------------------------------------


class TestCanonicalize:
    def test_ligature_expansion(self):
        assert canonical.canonicalize("the ﬁnal eﬃcient oﬀer") == "the final efficient offer"
        assert canonical.canonicalize("ﬂow ﬄuent æther œuvre") == "flow ffluent aether oeuvre"

    def test_dehyphenation_across_line_breaks(self):
        assert canonical.canonicalize("halluci-\nnation") == "hallucination"
        assert canonical.canonicalize("epis-  \n  temic foraging") == "epistemic foraging"
        # a hyphen not followed by a line break survives
        assert canonical.canonicalize("state-of-the-art") == "state-of-the-art"

    def test_whitespace_folding(self):
        assert canonical.canonicalize("  a \t b\n\n c   d  ") == "a b c d"

    def test_curly_quote_normalization(self):
        assert canonical.canonicalize("‘x’ and “y”") == "'x' and \"y\""
        # dashes normalize too
        assert canonical.canonicalize("A–B—C") == "A-B-C"

    def test_empty_and_none_safe(self):
        assert canonical.canonicalize("") == ""
        assert canonical.canonicalize(None) == ""


# ---------------------------------------------------------------------------
# 2. find_span
# ---------------------------------------------------------------------------


class TestFindSpan:
    def test_exact_match(self):
        span = find_span(ABSTRACT, "reduces hallucination rates")
        assert span is not None
        assert span.score == 1.0
        assert span.text == "reduces hallucination rates"
        assert ABSTRACT[span.start:span.end] == span.text

    def test_exact_match_is_case_insensitive(self):
        span = find_span(ABSTRACT, "RETRIEVAL AUGMENTED GENERATION")
        assert span is not None
        assert span.score == 1.0
        assert span.text == "Retrieval augmented generation"

    def test_approximate_match_above_threshold(self):
        # "lowers" vs "reduces": not a substring, but close enough to snap
        span = find_span(ABSTRACT, "augmented generation lowers hallucination rates")
        assert span is not None
        assert 0.72 <= span.score < 1.0
        assert "hallucination rates" in span.text

    def test_miss_returns_none(self):
        assert find_span(ABSTRACT, "zebras play chess underwater on tuesdays") is None

    def test_empty_inputs_return_none(self):
        assert find_span("", "anything") is None
        assert find_span(ABSTRACT, "") is None


# ---------------------------------------------------------------------------
# 3. ledger
# ---------------------------------------------------------------------------


class TestLedger:
    def test_entries_chain_and_verify(self, ws):
        ws.ask("q one?")
        ws.ask("q two?")
        ws.ask("q three?")
        entries = ws.store.ledger_entries()
        assert len(entries) == 3
        assert entries[0]["prev_hash"] == "0" * 64
        for prev, cur in zip(entries, entries[1:]):
            assert cur["prev_hash"] == prev["hash"]
        ok, msg = ws.store.verify_ledger()
        assert ok is True
        assert msg == "ledger intact"
        # the same surface via Workspace.log
        log = ws.log(verify=True)
        assert log["verified"] is True and log["total"] == 3

    def test_altered_entry_breaks_verification(self, ws):
        ws.ask("q one?")
        ws.ask("q two?")
        path = ws.store.ledger_path
        lines = path.read_text().splitlines()
        entry = json.loads(lines[1])
        entry["actor"] = "human:mallory"  # tamper with the second entry
        lines[1] = json.dumps(entry, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n")

        ok, msg = ws.store.verify_ledger()
        assert ok is False
        assert msg == "entry 2: hash mismatch (entry altered)"

    def test_broken_chain_is_reported(self, ws):
        ws.ask("q one?")
        ws.ask("q two?")
        path = ws.store.ledger_path
        lines = path.read_text().splitlines()
        entry = json.loads(lines[1])
        entry["prev_hash"] = "f" * 64  # detach entry 2 from entry 1
        lines[1] = json.dumps(entry, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n")

        ok, msg = ws.store.verify_ledger()
        assert ok is False
        assert msg == "entry 2: prev_hash mismatch (chain broken)"


# ---------------------------------------------------------------------------
# 4. pin
# ---------------------------------------------------------------------------


class TestPin:
    def test_verified_abstract_tier(self, ws):
        sid = add_source(ws, "RAG survey", abstract=ABSTRACT)
        ev = ws.pin(sid, quote="reduces hallucination rates")
        assert ev["verification"] == "verified-abstract"
        assert ev["quote"] == "reduces hallucination rates"

    def test_quote_verifies_through_canonicalization(self, ws):
        # curly quotes + ligature + reflowed whitespace still canonical-match
        sid = add_source(ws, "Canon paper", abstract='The "ﬁnal" answer is grounded.')
        ev = ws.pin(sid, quote="The “final” answer")
        assert ev["verification"] == "verified-abstract"
        assert ev["quote"] == 'The "final" answer'

    def test_non_matching_quote_raises_value_error(self, ws):
        sid = add_source(ws, "RAG survey 2", abstract=ABSTRACT)
        with pytest.raises(ValueError, match="canonical-match"):
            ws.pin(sid, quote="this sentence appears nowhere in the source")

    def test_unverified_locator_when_no_text(self, ws):
        sid = add_source(ws, "Paywalled paper", abstract=None)
        ev = ws.pin(sid, quote="anything at all", locator="p. 3")
        assert ev["verification"] == "unverified-locator"
        assert ev["locator"] == "p. 3"

    def test_quote_snap_via_find(self, ws):
        sid = add_source(ws, "RAG survey 3", abstract=ABSTRACT)
        ev = ws.pin(sid, find="augmented generation lowers hallucination rates")
        assert ev["verification"] == "verified-abstract"
        assert "hallucination rates" in ev["quote"]
        assert ev["locator"].startswith("chars ")

    def test_verified_full_text_tier_via_direct_insert(self, ws):
        text = canonical.canonicalize(ABSTRACT)
        ws.store.db.execute(
            "INSERT INTO sources(id, title, connector, read_status, text_status,"
            " abstract, text, extractor_version) VALUES(?,?,?,?,?,?,?,?)",
            ("src_full1", "Full text paper", "test", "unread", "full",
             text, text, EXTRACTOR_VERSION))
        ws.store.db.commit()
        ev = ws.pin("src_full1", quote="grounding every answer in cited sources")
        assert ev["verification"] == "verified-full-text"

    def test_pin_requires_quote_or_find(self, ws):
        sid = add_source(ws, "RAG survey 4", abstract=ABSTRACT)
        with pytest.raises(ValueError, match="--quote or --find"):
            ws.pin(sid)

    def test_pin_unknown_source(self, ws):
        with pytest.raises(KeyError):
            ws.pin("src_nope", quote="x")


# ---------------------------------------------------------------------------
# 5. claim status derivation is total
# ---------------------------------------------------------------------------


class TestClaimStatus:
    @pytest.fixture()
    def pins(self, ws):
        sid = add_source(ws, "Status paper", abstract=ABSTRACT)
        ev1 = ws.pin(sid, quote="reduces hallucination rates")
        ev2 = ws.pin(sid, quote="grounding every answer in cited sources")
        return ev1["id"], ev2["id"]

    def test_supports_only_is_supported(self, ws, pins):
        c = ws.add_claim("RAG reduces hallucinations", [(pins[0], "supports")])
        assert c["status"] == "supported"

    def test_any_contradicts_is_contested(self, ws, pins):
        c = ws.add_claim("RAG reduces hallucinations",
                         [(pins[0], "supports"), (pins[1], "contradicts")])
        assert c["status"] == "contested"

    def test_mentions_only_is_unsupported(self, ws, pins):
        c = ws.add_claim("RAG is mentioned somewhere", [(pins[0], "mentions")])
        assert c["status"] == "unsupported"

    def test_no_links_is_unsupported(self, ws):
        c = ws.add_claim("a bare assertion")
        assert c["status"] == "unsupported"

    def test_link_evidence_flips_status(self, ws, pins):
        c = ws.add_claim("starts supported", [(pins[0], "supports")])
        assert c["status"] == "supported"
        c = ws.link_evidence(c["id"], pins[1], "contradicts")
        assert c["status"] == "contested"

    def test_invalid_stance_rejected(self, ws, pins):
        with pytest.raises(ValueError, match="stance"):
            ws.add_claim("bad stance", [(pins[0], "refutes")])

    def test_stale_overlay_direct(self):
        # pure-function check: all supporting pins older than the cutoff
        links = [{"evidence_id": "ev1", "stance": "supports"}]
        old = {"ev1": {"retrieved_at": time.time() - 400 * 86400}}
        fresh = {"ev1": {"retrieved_at": time.time()}}
        assert synthesis.derive_status(links, old) == "stale"
        assert synthesis.derive_status(links, fresh) == "supported"


# ---------------------------------------------------------------------------
# 6. audit
# ---------------------------------------------------------------------------


class TestAudit:
    def test_flags_unsupported_single_source_and_orphan(self, ws):
        sid = add_source(ws, "Audit paper", abstract=ABSTRACT)
        ev1 = ws.pin(sid, quote="reduces hallucination rates")
        ws.pin(sid, quote="grounding every answer in cited sources")  # orphan
        c1 = ws.add_claim("single-sourced claim", [(ev1["id"], "supports")])
        c2 = ws.add_claim("claim with no evidence")

        result = ws.audit()
        assert result["ok"] is False
        kinds = {f["kind"] for f in result["findings"]}
        assert {"unsupported-claim", "single-source-claim", "orphaned-pin"} <= kinds
        assert result["counts"]["unsupported-claim"] == 1
        assert result["counts"]["single-source-claim"] == 1
        assert result["counts"]["orphaned-pin"] == 1

        by_kind = {f["kind"]: f for f in result["findings"]}
        assert by_kind["unsupported-claim"]["claim"] == c2["id"]
        assert by_kind["single-source-claim"]["claim"] == c1["id"]

    def test_clean_workspace_audits_ok(self, ws):
        assert ws.audit() == {"ok": True, "counts": {}, "findings": []}

    def test_two_source_claim_not_flagged_single(self, ws):
        s1 = add_source(ws, "Paper A", abstract=ABSTRACT, authors=["A One"])
        s2 = add_source(ws, "Paper B", abstract=ABSTRACT, authors=["B Two"])
        ev1 = ws.pin(s1, quote="reduces hallucination rates")
        ev2 = ws.pin(s2, quote="reduces hallucination rates")
        ws.add_claim("well sourced", [(ev1["id"], "supports"), (ev2["id"], "supports")])
        result = ws.audit()
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# 7. brief
# ---------------------------------------------------------------------------


@pytest.fixture()
def briefed(ws):
    q = ws.ask("Does RAG reduce hallucinations?")
    sid = add_source(ws, "RAG for factuality", abstract=ABSTRACT,
                     authors=["Grace Hopper", "Alan Turing"], year=2023)
    ev = ws.pin(sid, quote="reduces hallucination rates")
    c = ws.add_claim("RAG reduces hallucination rates",
                     [(ev["id"], "supports")], confidence=0.8,
                     questions=[q["id"]])
    return ws, q, ev, c


class TestBrief:
    def test_markdown_contains_claim_quote_and_tier(self, briefed):
        ws, q, ev, c = briefed
        md = ws.brief(q["id"])["markdown"]
        assert md.startswith(f"# Brief: {q['text']}")
        assert c["text"] in md
        assert ev["quote"] in md
        assert "verified-abstract" in md
        assert "Supported (1)" in md
        assert "Hopper et al. (2023)" in md

    def test_out_path_writes_file_and_returns_counts(self, briefed, tmp_path):
        ws, q, ev, c = briefed
        out = tmp_path / "brief.md"
        r = ws.brief(q["id"], out_path=str(out))
        assert r["path"] == str(out)
        assert r["claim_counts_by_status"] == {"supported": 1}
        content = out.read_text()
        assert c["text"] in content and ev["quote"] in content

    def test_badge_default_on_and_off(self, briefed):
        ws, q, _, _ = briefed
        assert "foraged with" in ws.brief(q["id"])["markdown"]
        assert "foraged with" not in ws.brief(q["id"], badge=False)["markdown"]


# ---------------------------------------------------------------------------
# 8. scoring
# ---------------------------------------------------------------------------


class TestScoring:
    SOURCES = [
        {"id": "s1", "title": "Epistemic foraging in research agents",
         "abstract": "foraging strategies for research agents and evidence",
         "year": 2024, "read_status": "unread", "text_status": "abstract-only"},
        {"id": "s2", "title": "Boiling pasta correctly",
         "abstract": "salt the water before cooking pasta",
         "year": 2020, "read_status": "unread", "text_status": "none"},
        {"id": "s3", "title": "Already-read foraging paper",
         "abstract": "foraging background material",
         "year": 2021, "read_status": "read", "text_status": "abstract-only"},
    ]

    def test_rank_frontier_returns_unread_only_ranked(self):
        ranked = scoring.rank_frontier("epistemic foraging agents",
                                       self.SOURCES, edges=[], top=10)
        ids = [r["id"] for r in ranked]
        assert set(ids) == {"s1", "s2"}  # the read source never appears
        assert ids[0] == "s1"            # relevant source outranks the off-topic one
        scores = [r["score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)
        for r in ranked:
            assert {"relevance", "novelty", "centrality", "cost"} <= set(r["components"])
            assert r["why"]

    def test_rank_frontier_respects_top(self):
        ranked = scoring.rank_frontier("foraging", self.SOURCES, edges=[], top=1)
        assert len(ranked) == 1

    def test_patch_yield_exhausted_after_zero_yield_window(self):
        zero = [{"source_id": f"s{i}", "pins": 0, "claims": 0} for i in range(4)]
        r = scoring.patch_yield(zero)
        assert r["patch_exhausted"] is True
        assert r["marginal_yield"] == 0
        assert "exhausted" in r["advice"]

    def test_patch_yield_not_exhausted_below_window(self):
        zero = [{"source_id": f"s{i}", "pins": 0, "claims": 0} for i in range(3)]
        r = scoring.patch_yield(zero)
        assert r["patch_exhausted"] is False

    def test_patch_yield_not_exhausted_with_yield(self):
        reads = [{"source_id": "s0", "pins": 1, "claims": 0}] + [
            {"source_id": f"s{i}", "pins": 0, "claims": 0} for i in range(1, 4)]
        r = scoring.patch_yield(reads)
        assert r["patch_exhausted"] is False
        assert r["marginal_yield"] == 1

    def test_workspace_patch_signal_exhausts(self, ws):
        for i in range(4):
            sid = add_source(ws, f"Zero-yield paper {i}", abstract="nothing here")
            ws.mark_read(sid, "read")
        status = ws.status()
        assert status["patch_exhausted"] is True
        assert status["unread_sources"] == 0

    def test_workspace_frontier_excludes_read(self, ws):
        ws.ask("epistemic foraging agents?")
        keep = add_source(ws, "Epistemic foraging in agents",
                          abstract="foraging strategies for agents")
        skip = add_source(ws, "Unrelated cooking paper", abstract="pasta water")
        ws.mark_read(skip, "read")
        ranked = ws.frontier()["ranked"]
        assert [r["id"] for r in ranked] == [keep]


# ---------------------------------------------------------------------------
# 9. CLI smoke test (subprocess, offline commands only)
# ---------------------------------------------------------------------------


def run_cli(tmp_path, *argv):
    return subprocess.run(
        [sys.executable, "-m", "foragekit.cli", "--workspace", str(tmp_path),
         "--json", *argv],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "FORAGE_ACTOR": "human:cli-test"})


class TestCLI:
    def test_init_ask_status_round_trip(self, tmp_path):
        r = run_cli(tmp_path, "init")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["workspace"] == str(tmp_path)
        assert (tmp_path / ".forage" / "forage.db").exists()

        r = run_cli(tmp_path, "ask", "Does RAG reduce hallucinations?",
                    "--uncertainty", "med")
        assert r.returncode == 0, r.stderr
        q = json.loads(r.stdout)
        assert q["id"] == "q1" and q["status"] == "open" and q["uncertainty"] == "med"

        r = run_cli(tmp_path, "status")
        assert r.returncode == 0, r.stderr
        status = json.loads(r.stdout)
        assert status["questions"] == 1
        assert status["sources"] == 0
        assert status["unread_sources"] == 0
        assert "advice" in status

    def test_cli_error_exit_code(self, tmp_path):
        run_cli(tmp_path, "init")
        r = run_cli(tmp_path, "sources", "show", "src_nope")
        assert r.returncode == 2
        assert "error:" in r.stderr

    def test_cli_log_verify(self, tmp_path):
        run_cli(tmp_path, "ask", "q?")
        r = run_cli(tmp_path, "log", "--verify")
        assert r.returncode == 0, r.stderr
        log = json.loads(r.stdout)
        assert log["verified"] is True
        assert log["entries"][0]["actor"] == "human:cli-test"


# ---------------------------------------------------------------------------
# 10. MCP server round trip (subprocess, stdio JSON-RPC)
# ---------------------------------------------------------------------------


class TestMCPServer:
    def test_initialize_list_call_and_ledger_actor(self, tmp_path):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "pytest-mcp", "version": "0.0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "forage_ask",
                        "arguments": {"question": "Does RAG reduce hallucinations?"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "forage_status", "arguments": {}}},
        ]
        payload = "".join(json.dumps(r) + "\n" for r in requests)
        proc = subprocess.run(
            [sys.executable, "-m", "foragekit.cli", "--workspace", str(tmp_path), "serve"],
            input=payload, capture_output=True, text=True, timeout=60,
            env={**os.environ, "FORAGE_ACTOR": "human:should-be-overridden"})
        assert proc.returncode == 0, proc.stderr

        replies = {m["id"]: m for m in map(json.loads, proc.stdout.splitlines())}

        init = replies[1]["result"]
        assert init["serverInfo"]["name"] == "foragekit"
        assert init["protocolVersion"] == "2025-06-18"

        assert replies[2]["result"] == {}  # ping

        tools = replies[3]["result"]["tools"]
        assert len(tools) == 21
        names = {t["name"] for t in tools}
        assert {"forage_ask", "forage_status", "forage_pin_evidence",
                "forage_brief", "forage_audit", "forage_log"} <= names
        assert all(t["inputSchema"]["type"] == "object" for t in tools)

        ask = replies[4]["result"]
        assert ask["isError"] is False
        asked = json.loads(ask["content"][0]["text"])
        assert asked["id"] == "q1"
        assert asked["text"] == "Does RAG reduce hallucinations?"

        status = replies[5]["result"]
        assert status["isError"] is False
        assert json.loads(status["content"][0]["text"])["questions"] == 1

        # writes are attributed to the MCP client, not the shell user
        ledger = [json.loads(l) for l in
                  (tmp_path / ".forage" / "ledger.jsonl").read_text().splitlines()]
        ask_entries = [e for e in ledger if e["action"] == "ask"]
        assert ask_entries and all(e["actor"] == "agent:pytest-mcp" for e in ask_entries)

    def test_tool_call_error_is_soft(self, tmp_path):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "pytest-mcp", "version": "0.0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "forage_get_claim", "arguments": {"claim_id": "c99"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "bogus/method"},
        ]
        payload = "".join(json.dumps(r) + "\n" for r in requests)
        proc = subprocess.run(
            [sys.executable, "-m", "foragekit.cli", "--workspace", str(tmp_path), "serve"],
            input=payload, capture_output=True, text=True, timeout=60,
            env={**os.environ})
        assert proc.returncode == 0, proc.stderr
        replies = {m["id"]: m for m in map(json.loads, proc.stdout.splitlines())}
        bad_call = replies[2]["result"]
        assert bad_call["isError"] is True
        assert "c99" in bad_call["content"][0]["text"]
        assert replies[3]["error"]["code"] == -32601
