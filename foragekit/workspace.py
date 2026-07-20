"""The Workspace: every surface (CLI, MCP, Python) goes through here."""
from __future__ import annotations

import difflib
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from . import canonical, scoring, synthesis
from .canonical import EXTRACTOR_VERSION
from .connectors import CONNECTORS, SourceRecord, fetch_arxiv_html
from .store import Store, default_actor

# Blocked fuzzy dedup (preprint <-> published): candidates share the first
# _BLOCK_CHARS chars of the normalized title; within a block a pair merges when
# the full-title similarity beats _FUZZY_RATIO and the first author matches.
_BLOCK_CHARS = 25
_FUZZY_RATIO = 0.92


def _first_author_lastname(authors: list[str]) -> str | None:
    if not authors or not (authors[0] or "").strip():
        return None
    name = authors[0].strip()
    if "," in name:  # "Lovelace, Ada" -> "Lovelace"
        name = name.split(",", 1)[0].strip()
    parts = name.split()
    return parts[-1].lower() if parts else None


class Workspace:
    def __init__(self, root: str | Path = "."):
        self.store = Store(Path(root))
        self.actor = default_actor()

    @classmethod
    def open(cls, root: str | Path = ".") -> "Workspace":
        return cls(root)

    def _rec(self, action: str, entity: str, payload: dict):
        self.store.record(self.actor, action, entity, payload)

    # -- questions ----------------------------------------------------------
    def ask(self, text: str, uncertainty: str = "high") -> dict:
        qid = self.store.next_id("question", "q")
        self.store.db.execute(
            "INSERT INTO questions(id, text, uncertainty, created_at) VALUES(?,?,?,?)",
            (qid, text, uncertainty, time.time()))
        self.store.db.commit()
        self._rec("ask", qid, {"text": text, "uncertainty": uncertainty})
        return {"id": qid, "text": text, "status": "open", "uncertainty": uncertainty}

    def list_questions(self) -> list[dict]:
        rows = self.store.db.execute("SELECT * FROM questions ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def update_question(self, qid: str, status: str | None = None,
                        uncertainty: str | None = None, note: str | None = None) -> dict:
        row = self.store.db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        if not row:
            raise KeyError(f"no question {qid}")
        status = status or row["status"]
        uncertainty = uncertainty or row["uncertainty"]
        self.store.db.execute(
            "UPDATE questions SET status=?, uncertainty=?, resolution_note=? WHERE id=?",
            (status, uncertainty, note or row["resolution_note"], qid))
        self.store.db.commit()
        self._rec("update_question", qid, {"status": status, "uncertainty": uncertainty})
        return self.get_question(qid)

    def get_question(self, qid: str) -> dict:
        row = self.store.db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        if not row:
            raise KeyError(f"no question {qid}")
        return dict(row)

    # -- sources --------------------------------------------------------------
    def _upsert(self, rec: SourceRecord, patch: str) -> tuple[str, bool]:
        sid = Store.source_id(rec.dedupe_key())
        existing = self.store.db.execute(
            "SELECT id FROM sources WHERE id=?", (sid,)).fetchone()
        if existing:
            return sid, False
        nt = canonical.norm_title(rec.title)
        fuzzy = self._fuzzy_duplicate(nt, rec)
        if fuzzy:
            return fuzzy, False
        abstract = canonical.canonicalize(rec.abstract) if rec.abstract else None
        self.store.db.execute(
            "INSERT INTO sources(id, openalex_id, doi, arxiv_id, title, authors, year,"
            " venue, urls, connector, retrieved_at, text_status, abstract, text,"
            " extractor_version, patch, norm_title) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, rec.openalex_id, rec.doi, rec.arxiv_id, rec.title,
             json.dumps(rec.authors), rec.year, rec.venue, json.dumps(rec.urls),
             rec.connector, time.time(),
             "abstract-only" if abstract else "none",
             abstract, abstract, EXTRACTOR_VERSION, patch, nt))
        return sid, True

    def _fuzzy_duplicate(self, nt: str, rec: SourceRecord) -> str | None:
        """Blocked fuzzy dedup for the preprint <-> published case.

        Candidates come from an indexed prefix-range lookup on norm_title
        (no O(n^2) scan); a candidate merges only when the full normalized
        titles are near-identical AND the first-author last name matches.
        """
        block = nt[:_BLOCK_CHARS]
        if not block:
            return None
        hi = block[:-1] + chr(ord(block[-1]) + 1)  # indexed prefix range
        rows = self.store.db.execute(
            "SELECT id, norm_title, authors FROM sources"
            " WHERE norm_title >= ? AND norm_title < ?", (block, hi)).fetchall()
        mine = _first_author_lastname(rec.authors)
        if not mine:
            return None
        matcher = difflib.SequenceMatcher(autojunk=False)
        matcher.set_seq2(nt)
        for r in rows:
            if not r["norm_title"]:
                continue
            matcher.set_seq1(r["norm_title"])
            if matcher.ratio() <= _FUZZY_RATIO:
                continue
            theirs = _first_author_lastname(json.loads(r["authors"] or "[]"))
            if theirs and theirs == mine:
                return r["id"]
        return None

    def search(self, query: str, connectors: list[str] | None = None,
               limit: int = 25) -> dict:
        names = connectors or ["openalex"]
        patch = f"search:{query[:60]}"
        added, merged, ids = 0, 0, []
        for name in names:
            conn = CONNECTORS.get(name)
            if not conn:
                raise KeyError(f"unknown connector {name!r} (have: {list(CONNECTORS)})")
            for rec in conn.search(query, limit=limit):
                sid, is_new = self._upsert(rec, patch)
                ids.append(sid)
                added += is_new
                merged += (not is_new)
        self.store.db.commit()
        self._rec("search", patch, {"query": query, "connectors": names,
                                    "added": added, "merged": merged})
        return {"added": added, "merged": merged, "source_ids": ids,
                "patch": patch}

    def snowball(self, source_id: str, direction: str = "both",
                 budget: int = 40) -> dict:
        src = self.get_source(source_id)
        oa = src.get("openalex_id")
        if not oa:
            raise ValueError(f"{source_id} has no OpenAlex id; snowballing needs one "
                             "(search openalex for it first)")
        patch = f"snowball:{source_id}"
        conn = CONNECTORS["openalex"]
        added, ids = 0, []
        if direction in ("back", "both"):
            refs = (src.get("_referenced") or [])[:budget]
            for rec in conn.lookup_many(refs):
                sid, is_new = self._upsert(rec, patch)
                added += is_new
                ids.append(sid)
                self.store.db.execute(
                    "INSERT OR IGNORE INTO edges(src, dst) VALUES(?,?)", (source_id, sid))
        if direction in ("fwd", "both"):
            for rec in conn.cited_by(oa, limit=min(budget, 50)):
                sid, is_new = self._upsert(rec, patch)
                added += is_new
                ids.append(sid)
                self.store.db.execute(
                    "INSERT OR IGNORE INTO edges(src, dst) VALUES(?,?)", (sid, source_id))
        self.store.db.commit()
        self._rec("snowball", source_id, {"direction": direction, "added": added})
        return {"added": added, "source_ids": ids, "patch": patch}

    def list_sources(self, read_status: str | None = None, limit: int = 50,
                     offset: int = 0) -> list[dict]:
        q = ("SELECT id, title, year, connector, read_status, text_status "
             "FROM sources")
        args: list = []
        if read_status:
            q += " WHERE read_status=?"
            args.append(read_status)
        q += " ORDER BY retrieved_at LIMIT ? OFFSET ?"
        args += [limit, offset]
        return [dict(r) for r in self.store.db.execute(q, args).fetchall()]

    def get_source(self, source_id: str) -> dict:
        row = self.store.db.execute("SELECT * FROM sources WHERE id=?",
                                    (source_id,)).fetchone()
        if not row:
            raise KeyError(f"no source {source_id}")
        d = dict(row)
        d["authors"] = json.loads(d.get("authors") or "[]")
        d["urls"] = json.loads(d.get("urls") or "[]")
        d["_referenced"] = []
        if d.get("openalex_id"):
            # referenced works are re-fetched on demand for snowballing
            recs = CONNECTORS["openalex"].lookup_many([d["openalex_id"]])
            if recs:
                d["_referenced"] = recs[0].referenced
        text = d.pop("text", None)
        d["text_chars"] = len(text) if text else 0
        return d

    def fetch_text(self, source_id: str) -> dict:
        """Full-text tier (M3): cache the arXiv HTML render when the source
        has an arxiv_id. Allowlist-only (arxiv.org) — no generic URL fetch;
        everything else honestly stays at the abstract tier (SPEC §2.1)."""
        row = self.store.db.execute(
            "SELECT text_status, abstract, arxiv_id FROM sources WHERE id=?",
            (source_id,)).fetchone()
        if not row:
            raise KeyError(f"no source {source_id}")
        current = row["text_status"]
        fallback = "abstract-only" if row["abstract"] else "none"
        if current == "cached-full":
            return {"source_id": source_id, "text_status": "cached-full",
                    "reason": "full text already cached"}
        if not row["arxiv_id"]:
            if row["abstract"]:
                return {"source_id": source_id, "text_status": "abstract-only",
                        "reason": "no allowlisted full-text host for this source "
                                  "(arXiv HTML is the only full-text tier); abstract cached"}
            return {"source_id": source_id, "text_status": "none",
                    "reason": "connector returned no abstract and source has no "
                              "allowlisted full-text host"}
        try:
            full = fetch_arxiv_html(row["arxiv_id"])
        except OSError as e:  # network/HTTP failure other than a clean 404
            return {"source_id": source_id, "text_status": fallback,
                    "reason": f"arXiv HTML fetch failed: {e}"}
        if full is None:
            return {"source_id": source_id, "text_status": fallback,
                    "reason": "no HTML render upstream"}
        text = canonical.canonicalize(full)
        self.store.db.execute(
            "UPDATE sources SET text=?, text_status='cached-full',"
            " extractor_version=? WHERE id=?",
            (text, EXTRACTOR_VERSION, source_id))
        self.store.db.commit()
        self._rec("fetch_text", source_id,
                  {"text_status": "cached-full", "chars": len(text),
                   "arxiv_id": row["arxiv_id"]})
        return {"source_id": source_id, "text_status": "cached-full",
                "reason": f"arXiv HTML render cached ({len(text)} chars)",
                "text_chars": len(text)}

    def get_source_text(self, source_id: str, start: int = 0,
                        max_chars: int = 2000) -> dict:
        row = self.store.db.execute(
            "SELECT text, read_status FROM sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            raise KeyError(f"no source {source_id}")
        text = row["text"] or ""
        if row["read_status"] == "unread":
            self.mark_read(source_id, "skimmed")
        return {"source_id": source_id, "start": start,
                "text": text[start:start + max_chars],
                "total_chars": len(text)}

    def find_text(self, source_id: str, query: str) -> dict:
        row = self.store.db.execute("SELECT text FROM sources WHERE id=?",
                                    (source_id,)).fetchone()
        if not row or not row["text"]:
            return {"found": False, "reason": "no cached text (try fetch_text)"}
        span = canonical.find_span(row["text"], query)
        if not span:
            return {"found": False, "reason": "no close span; rephrase the query"}
        return {"found": True, **asdict(span), "source_id": source_id}

    def mark_read(self, source_id: str, status: str = "read") -> dict:
        if status not in ("skimmed", "read"):
            raise ValueError("status must be skimmed|read")
        self.store.db.execute("UPDATE sources SET read_status=? WHERE id=?",
                              (status, source_id))
        self.store.db.commit()
        self._rec("mark_read", source_id, {"status": status})
        return {"source_id": source_id, "read_status": status}

    # -- evidence & claims ----------------------------------------------------
    def pin(self, source_id: str, quote: str | None = None,
            find: str | None = None, locator: str | None = None,
            note: str | None = None) -> dict:
        src_row = self.store.db.execute(
            "SELECT text, text_status FROM sources WHERE id=?", (source_id,)).fetchone()
        if not src_row:
            raise KeyError(f"no source {source_id}")
        text = src_row["text"] or ""
        if find and not quote:
            span = canonical.find_span(text, find)
            if not span:
                raise ValueError("quote-snap found no close span; rephrase --find")
            quote = span.text
            locator = locator or f"chars {span.start}-{span.end}"
        if not quote:
            raise ValueError("provide --quote or --find")
        cq = canonical.canonicalize(quote)
        if text and cq.lower() in canonical.canonicalize(text).lower():
            verification = ("verified-abstract" if src_row["text_status"] == "abstract-only"
                            else "verified-full-text")
        elif text:
            raise ValueError("quote does not canonical-match the cached text; "
                             "use --find for quote-snapping")
        else:
            verification = "unverified-locator"
        ev_id = self.store.next_id("evidence", "ev")
        self.store.db.execute(
            "INSERT INTO evidence(id, source_id, quote, locator, content_hash,"
            " verification, extractor_version, retrieved_at, note)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (ev_id, source_id, cq, locator,
             hashlib.sha256(cq.encode()).hexdigest(), verification,
             EXTRACTOR_VERSION, time.time(), note))
        self.store.db.commit()
        self._rec("pin", ev_id, {"source_id": source_id, "verification": verification,
                                 "quote": cq[:120]})
        return {"id": ev_id, "source_id": source_id, "quote": cq,
                "locator": locator, "verification": verification}

    def add_claim(self, text: str, evidence: list[tuple[str, str]] | None = None,
                  confidence: float | None = None,
                  questions: list[str] | None = None) -> dict:
        cid = self.store.next_id("claim", "c")
        self.store.db.execute(
            "INSERT INTO claims(id, text, confidence, created_by, created_at)"
            " VALUES(?,?,?,?,?)", (cid, text, confidence, self.actor, time.time()))
        for ev_id, stance in (evidence or []):
            self._link(cid, ev_id, stance)
        for qid in (questions or []):
            self.store.db.execute(
                "INSERT OR IGNORE INTO claim_questions(claim_id, question_id) VALUES(?,?)",
                (cid, qid))
        self.store.db.commit()
        self._rec("add_claim", cid, {"text": text[:120], "confidence": confidence,
                                     "evidence": [e for e, _ in (evidence or [])]})
        return self.get_claim(cid)

    def _link(self, claim_id: str, evidence_id: str, stance: str):
        if stance not in synthesis.STANCES:
            raise ValueError(f"stance must be one of {synthesis.STANCES}")
        if not self.store.db.execute("SELECT 1 FROM evidence WHERE id=?",
                                     (evidence_id,)).fetchone():
            raise KeyError(f"no evidence {evidence_id}")
        self.store.db.execute(
            "INSERT OR REPLACE INTO claim_links(claim_id, evidence_id, stance)"
            " VALUES(?,?,?)", (claim_id, evidence_id, stance))

    def link_evidence(self, claim_id: str, evidence_id: str, stance: str) -> dict:
        self._link(claim_id, evidence_id, stance)
        self.store.db.commit()
        self._rec("link_evidence", claim_id, {"evidence_id": evidence_id, "stance": stance})
        return self.get_claim(claim_id)

    def get_claim(self, claim_id: str) -> dict:
        row = self.store.db.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not row:
            raise KeyError(f"no claim {claim_id}")
        d = dict(row)
        d["links"] = [dict(r) for r in self.store.db.execute(
            "SELECT evidence_id, stance FROM claim_links WHERE claim_id=?", (claim_id,))]
        d["status"] = synthesis.derive_status(d["links"], self._evidence_by_id())
        return d

    def get_evidence(self, evidence_id: str) -> dict:
        row = self.store.db.execute("SELECT * FROM evidence WHERE id=?",
                                    (evidence_id,)).fetchone()
        if not row:
            raise KeyError(f"no evidence {evidence_id}")
        return dict(row)

    # -- foraging & synthesis --------------------------------------------------
    def _all_source_rows(self) -> list[dict]:
        return [dict(r) for r in self.store.db.execute(
            "SELECT id, title, abstract, year, read_status, text_status FROM sources")]

    def frontier(self, question_id: str | None = None, top: int = 10) -> dict:
        if question_id:
            q_text = self.get_question(question_id)["text"]
        else:
            qs = [q for q in self.list_questions() if q["status"] == "open"]
            q_text = " ".join(q["text"] for q in qs)
        edges = [(r["src"], r["dst"]) for r in self.store.db.execute("SELECT * FROM edges")]
        ranked = scoring.rank_frontier(q_text, self._all_source_rows(), edges, top=top)
        self._rec("frontier", question_id or "all", {"top": top, "weights": scoring.WEIGHTS})
        return {"ranked": ranked, **self._patch_signal()}

    def _patch_signal(self) -> dict:
        reads = [e for e in self.store.ledger_entries() if e["action"] == "mark_read"]
        recent = []
        for e in reversed(reads[-8:]):
            sid = e["entity"]
            pins = self.store.db.execute(
                "SELECT COUNT(*) FROM evidence WHERE source_id=?", (sid,)).fetchone()[0]
            claims = self.store.db.execute(
                "SELECT COUNT(DISTINCT claim_id) FROM claim_links JOIN evidence"
                " ON evidence.id = claim_links.evidence_id WHERE evidence.source_id=?",
                (sid,)).fetchone()[0]
            recent.append({"source_id": sid, "pins": pins, "claims": claims})
        return scoring.patch_yield(recent)

    def _evidence_by_id(self) -> dict:
        return {r["id"]: dict(r) for r in self.store.db.execute("SELECT * FROM evidence")}

    def _sources_by_id(self) -> dict:
        out = {}
        for r in self.store.db.execute("SELECT * FROM sources"):
            d = dict(r)
            d["authors"] = json.loads(d.get("authors") or "[]")
            out[d["id"]] = d
        return out

    def _claims_for(self, question_id: str | None) -> tuple[list[dict], dict]:
        if question_id:
            rows = self.store.db.execute(
                "SELECT claims.* FROM claims JOIN claim_questions"
                " ON claims.id = claim_questions.claim_id WHERE question_id=?",
                (question_id,)).fetchall()
        else:
            rows = self.store.db.execute("SELECT * FROM claims").fetchall()
        claims = [dict(r) for r in rows]
        links = {c["id"]: [dict(r) for r in self.store.db.execute(
            "SELECT evidence_id, stance FROM claim_links WHERE claim_id=?", (c["id"],))]
            for c in claims}
        return claims, links

    def brief(self, question_id: str, badge: bool = True,
              out_path: str | None = None) -> dict:
        q = self.get_question(question_id)
        claims, links = self._claims_for(question_id)
        md = synthesis.compile_brief(q, claims, links, self._evidence_by_id(),
                                     self._sources_by_id(), badge=badge)
        self._rec("brief", question_id, {"claims": len(claims)})
        if out_path:
            Path(out_path).write_text(md)
            statuses: dict[str, int] = {}
            ev = self._evidence_by_id()
            for c in claims:
                s = synthesis.derive_status(links.get(c["id"], []), ev)
                statuses[s] = statuses.get(s, 0) + 1
            return {"path": out_path, "claim_counts_by_status": statuses}
        return {"markdown": md}

    def audit(self) -> dict:
        claims, links = self._claims_for(None)
        result = synthesis.audit(claims, links, self._evidence_by_id(), self._sources_by_id())
        self._rec("audit", "workspace", {"counts": result["counts"]})
        return result

    def status(self) -> dict:
        counts = {t: self.store.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("questions", "sources", "evidence", "claims")}
        unread = self.store.db.execute(
            "SELECT COUNT(*) FROM sources WHERE read_status='unread'").fetchone()[0]
        return {**counts, "unread_sources": unread, **self._patch_signal()}

    def log(self, limit: int = 20, verify: bool = False) -> dict:
        entries = self.store.ledger_entries()
        out = {"entries": entries[-limit:], "total": len(entries)}
        if verify:
            ok, msg = self.store.verify_ledger()
            out["verified"] = ok
            out["verify_message"] = msg
        return out

    def export(self, fmt: str = "bibtex") -> str:
        if fmt != "bibtex":
            raise ValueError("only bibtex in the walking skeleton")
        return synthesis.export_bibtex(list(self._sources_by_id().values()))
