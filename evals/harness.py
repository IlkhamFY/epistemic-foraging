"""Core harness: discovery strategies, recall, and the ordering proxy."""
from __future__ import annotations

import json
import re
from pathlib import Path

from foragekit import Workspace, connectors, scoring

_STOP = set("a an and are as at be by do does for from has have in is it its of "
            "on or that the to was were will with how what why when large".split())

RELEVANCE_ONLY = {"relevance": 1.0, "novelty": 0.0, "centrality": 0.0, "cost": 0.0}


def load_dataset(path: str | Path) -> dict:
    d = json.loads(Path(path).read_text())
    for key in ("name", "question", "seed_openalex_ids", "target_openalex_ids"):
        if key not in d:
            raise ValueError(f"dataset missing {key!r}")
    return d


def query_variants(question: str) -> list[str]:
    words = [w for w in re.findall(r"[A-Za-z0-9-]+", question.lower()) if w not in _STOP]
    keywords = " ".join(words)
    return list(dict.fromkeys([question, keywords, keywords + " survey"]))


def _under(budget: int) -> bool:
    return connectors.request_count() < budget


def discover_keyword(ws: Workspace, question: str, budget: int) -> None:
    """Baseline: keyword searches only, no citation walking."""
    for q in query_variants(question):
        for conn in ("openalex", "arxiv"):
            if not _under(budget):
                return
            try:
                ws.search(q, [conn], limit=50)
            except Exception:
                continue


def discover_forage(ws: Workspace, question: str, seed_ids: list[str],
                    budget: int) -> None:
    """Foraging: two searches, snowball the seeds, then keep expanding from
    the best-connected unexplored node until the request budget is spent —
    iterative, citation-guided patch hopping rather than one fixed pass."""
    for q in query_variants(question)[:2]:
        if _under(budget):
            ws.search(q, ["openalex"], limit=50)
    if not _under(budget):
        return
    recs = connectors.CONNECTORS["openalex"].lookup_many(seed_ids)
    queue = []
    for rec in recs:
        sid, _ = ws._upsert(rec, patch="eval-seed")
        queue.append(sid)
    ws.store.db.commit()
    snowballed: set[str] = set()
    while _under(budget):
        sid = queue.pop(0) if queue else _next_hub(ws, snowballed)
        if sid is None:
            return
        if sid in snowballed:
            continue
        snowballed.add(sid)
        try:
            ws.snowball(sid, direction="both", budget=50)
        except Exception:
            continue


def _next_hub(ws: Workspace, done: set[str]) -> str | None:
    """Highest citation-degree source in the workspace not yet snowballed."""
    rows = ws.store.db.execute(
        "SELECT s.id AS sid, COUNT(*) AS deg FROM sources s"
        " JOIN edges e ON e.src = s.id OR e.dst = s.id"
        " WHERE s.openalex_id IS NOT NULL"
        " GROUP BY s.id ORDER BY deg DESC").fetchall()
    for r in rows:
        if r["sid"] not in done:
            return r["sid"]
    return None


def discovered_openalex_ids(ws: Workspace) -> set[str]:
    rows = ws.store.db.execute(
        "SELECT openalex_id FROM sources WHERE openalex_id IS NOT NULL").fetchall()
    return {r["openalex_id"] for r in rows}


def recall(ws: Workspace, targets: list[str]) -> float:
    if not targets:
        return 0.0
    return len(discovered_openalex_ids(ws) & set(targets)) / len(targets)


def ordering_recall(ws: Workspace, question: str, targets: list[str],
                    ks: tuple[int, ...] = (10, 25)) -> dict:
    """SPEC §6.4 proxy: over the same discovered pool, does frontier ordering
    surface hidden targets earlier than relevance-only ordering?"""
    rows = [dict(r) for r in ws.store.db.execute(
        "SELECT id, title, abstract, year, read_status, text_status, openalex_id"
        " FROM sources")]
    oa_by_id = {r["id"]: r.get("openalex_id") for r in rows}
    pool_targets = {r["id"] for r in rows if r.get("openalex_id") in set(targets)}
    edges = [(r["src"], r["dst"]) for r in ws.store.db.execute("SELECT * FROM edges")]
    out: dict = {"targets_in_pool": len(pool_targets)}
    for label, weights in (("frontier", None), ("relevance_only", RELEVANCE_ONLY)):
        ranked = scoring.rank_frontier(question, rows, edges,
                                       top=len(rows), weights=weights)
        order = [r["id"] for r in ranked]
        out[label] = {
            f"recall@{k}": (len(set(order[:k]) & pool_targets) / len(pool_targets)
                            if pool_targets else 0.0)
            for k in ks
        }
        out[label]["first_target_rank"] = next(
            (i + 1 for i, sid in enumerate(order) if sid in pool_targets), None)
    # oa_by_id kept for callers that want per-item detail
    out["_oa_by_id_size"] = len(oa_by_id)
    return out
