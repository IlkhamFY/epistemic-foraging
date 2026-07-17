"""SQLite system-of-record plus the hash-chained JSONL ledger."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions(
  id TEXT PRIMARY KEY, text TEXT NOT NULL, status TEXT DEFAULT 'open',
  uncertainty TEXT DEFAULT 'high', created_at REAL, resolution_note TEXT);
CREATE TABLE IF NOT EXISTS sources(
  id TEXT PRIMARY KEY, openalex_id TEXT, doi TEXT, arxiv_id TEXT,
  title TEXT, authors TEXT, year INTEGER, venue TEXT, urls TEXT,
  connector TEXT, retrieved_at REAL, read_status TEXT DEFAULT 'unread',
  text_status TEXT DEFAULT 'none', abstract TEXT, text TEXT,
  extractor_version TEXT, patch TEXT);
CREATE TABLE IF NOT EXISTS evidence(
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL, quote TEXT NOT NULL,
  locator TEXT, content_hash TEXT, verification TEXT,
  extractor_version TEXT, retrieved_at REAL, note TEXT);
CREATE TABLE IF NOT EXISTS claims(
  id TEXT PRIMARY KEY, text TEXT NOT NULL, confidence REAL,
  created_by TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS claim_links(
  claim_id TEXT, evidence_id TEXT, stance TEXT,
  PRIMARY KEY (claim_id, evidence_id));
CREATE TABLE IF NOT EXISTS claim_questions(
  claim_id TEXT, question_id TEXT, PRIMARY KEY (claim_id, question_id));
CREATE TABLE IF NOT EXISTS edges(
  src TEXT, dst TEXT, PRIMARY KEY (src, dst));
CREATE TABLE IF NOT EXISTS counters(name TEXT PRIMARY KEY, value INTEGER);
"""

GENESIS = "0" * 64


def _canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / ".forage"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "forage.db")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.ledger_path = self.dir / "ledger.jsonl"

    # -- ids ---------------------------------------------------------------
    def next_id(self, name: str, prefix: str) -> str:
        cur = self.db.execute(
            "INSERT INTO counters(name, value) VALUES(?, 1) "
            "ON CONFLICT(name) DO UPDATE SET value = value + 1 RETURNING value",
            (name,),
        )
        n = cur.fetchone()[0]
        self.db.commit()
        return f"{prefix}{n}"

    @staticmethod
    def source_id(key: str) -> str:
        return "src_" + hashlib.sha256(key.encode()).hexdigest()[:6]

    # -- ledger ------------------------------------------------------------
    def _last_hash(self) -> str:
        if not self.ledger_path.exists():
            return GENESIS
        last = None
        with self.ledger_path.open() as fh:
            for line in fh:
                if line.strip():
                    last = line
        return json.loads(last)["hash"] if last else GENESIS

    def record(self, actor: str, action: str, entity: str, payload: dict) -> dict:
        entry = {
            "ts": round(time.time(), 3),
            "actor": actor,
            "action": action,
            "entity": entity,
            "payload_hash": hashlib.sha256(_canonical_json(payload).encode()).hexdigest(),
            "prev_hash": self._last_hash(),
        }
        entry["hash"] = hashlib.sha256(
            (entry["prev_hash"] + _canonical_json({k: v for k, v in entry.items() if k != "hash"})).encode()
        ).hexdigest()
        with self.ledger_path.open("a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def ledger_entries(self) -> list[dict]:
        if not self.ledger_path.exists():
            return []
        with self.ledger_path.open() as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def verify_ledger(self) -> tuple[bool, str]:
        prev = GENESIS
        for i, entry in enumerate(self.ledger_entries(), 1):
            if entry.get("prev_hash") != prev:
                return False, f"entry {i}: prev_hash mismatch (chain broken)"
            expect = hashlib.sha256(
                (entry["prev_hash"] + _canonical_json({k: v for k, v in entry.items() if k != "hash"})).encode()
            ).hexdigest()
            if entry.get("hash") != expect:
                return False, f"entry {i}: hash mismatch (entry altered)"
            prev = entry["hash"]
        return True, "ledger intact"


def default_actor() -> str:
    if os.environ.get("FORAGE_ACTOR"):
        return os.environ["FORAGE_ACTOR"]
    return f"human:{os.environ.get('USER', 'unknown')}"
