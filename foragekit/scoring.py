"""Frontier ranking: the epistemic-foraging core.

score = w_r*relevance + w_n*novelty + w_c*centrality - w_k*cost

Transparent heuristic per SPEC §2.2: BM25-lite relevance, TF-IDF-cosine
novelty against the centroid of already-read sources, citation-degree
centrality within the workspace graph. Weights are configurable and logged.
"""
from __future__ import annotations

import math
import re
from collections import Counter

WEIGHTS = {"relevance": 0.45, "novelty": 0.25, "centrality": 0.30, "cost": 1.0}
_STOP = set("a an and are as at be by for from has have in is it its of on or "
            "that the to was were will with we this those these do does not".split())


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if t not in _STOP and len(t) > 2]


def _tfidf(tokens: list[str], df: Counter, n_docs: int) -> dict[str, float]:
    tf = Counter(tokens)
    return {t: (1 + math.log(c)) * math.log((n_docs + 1) / (1 + df[t]))
            for t, c in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(t, 0.0) for t, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _bm25(q_tokens: set[str], toks: list[str], df: Counter,
          n_docs: int, avg_len: float, k1: float = 1.5, b: float = 0.75) -> float:
    """Okapi BM25 over one document: sum over question terms t present in the
    doc of IDF(t) * tf*(k1+1)/(tf + k1*(1-b+b*len/avg_len)), with
    IDF(t) = ln((N+1)/(1+df_t)). Full derivation in docs/SCORING.md."""
    if not toks:
        return 0.0
    tf = Counter(toks)
    norm = k1 * (1 - b + b * len(toks) / avg_len)
    return sum(
        math.log((n_docs + 1) / (1 + df[t])) * (tf[t] * (k1 + 1)) / (tf[t] + norm)
        for t in q_tokens if t in tf)


def score_passages(question: str, passages: list[str]) -> list[float]:
    """Library-mode relevance scorer for external RAG pipelines.

    Scores each passage against `question` with BM25 (IDF computed over this
    batch of passages) and normalizes to [0, 1] by the batch maximum, so the
    result is directly usable as `scores = score_passages(q, retrieved_texts)`
    inside your own writer/reviewer loop - no workspace, no network, no model
    call, no context-window expansion. Deterministic and O(total tokens).
    """
    docs = [_tokens(p) for p in passages]
    df = Counter(t for toks in docs for t in set(toks))
    n = max(1, len(docs))
    avg_len = sum(len(t) for t in docs) / n or 1.0
    q_tokens = set(_tokens(question))
    raw = [_bm25(q_tokens, toks, df, n, avg_len) for toks in docs]
    mx = max(raw, default=0.0)
    return [r / mx if mx else 0.0 for r in raw]


def rank_frontier(question_text: str, sources: list[dict],
                  edges: list[tuple[str, str]], top: int = 10,
                  weights: dict | None = None) -> list[dict]:
    """sources: dicts with id, title, abstract, read_status, text_status."""
    w = {**WEIGHTS, **(weights or {})}
    docs = {s["id"]: _tokens((s.get("title") or "") + " " + (s.get("abstract") or ""))
            for s in sources}
    df = Counter(t for toks in docs.values() for t in set(toks))
    n = max(1, len(docs))
    vecs = {sid: _tfidf(toks, df, n) for sid, toks in docs.items()}

    # BM25 relevance: idf-weighted overlap with the question (see _bm25)
    q_tokens = set(_tokens(question_text))
    avg_len = sum(len(t) for t in docs.values()) / n or 1.0

    def relevance(sid: str) -> float:
        return _bm25(q_tokens, docs[sid], df, n, avg_len)

    # novelty: distance from centroid of read sources
    read_ids = [s["id"] for s in sources if s.get("read_status") in ("skimmed", "read")]
    centroid: dict[str, float] = {}
    for rid in read_ids:
        for t, v in vecs[rid].items():
            centroid[t] = centroid.get(t, 0.0) + v / len(read_ids)

    degree = Counter()
    for a, b2 in edges:
        degree[a] += 1
        degree[b2] += 1
    max_deg = max(degree.values(), default=1)

    rel_raw = {s["id"]: relevance(s["id"]) for s in sources}
    max_rel = max(rel_raw.values(), default=1.0) or 1.0

    ranked = []
    for s in sources:
        if s.get("read_status") in ("skimmed", "read"):
            continue
        sid = s["id"]
        rel = rel_raw[sid] / max_rel
        nov = 1.0 - _cosine(vecs[sid], centroid) if centroid else 0.5
        cen = degree.get(sid, 0) / max_deg
        cost = 0.0 if s.get("text_status") != "none" else 0.15
        score = w["relevance"] * rel + w["novelty"] * nov + w["centrality"] * cen - w["cost"] * cost
        why = []
        if rel > 0.6:
            why.append("highly relevant to the question")
        if nov > 0.7 and centroid:
            why.append("outside the cluster you've already read")
        if cen > 0.5:
            why.append("central in the citation neighborhood")
        if cost:
            why.append("no cached text (costlier to verify)")
        ranked.append({
            "id": sid, "title": s.get("title"), "year": s.get("year"),
            "score": round(score, 3),
            "components": {"relevance": round(rel, 3), "novelty": round(nov, 3),
                           "centrality": round(cen, 3), "cost": cost},
            "why": "; ".join(why) or "moderate signal on all components",
        })
    ranked.sort(key=lambda r: -r["score"])
    return ranked[:top]


def patch_yield(recent_reads: list[dict], window: int = 4) -> dict:
    """recent_reads: [{source_id, pins, claims}] most-recent-first."""
    recent = recent_reads[:window]
    gained = sum(r["pins"] + r["claims"] for r in recent)
    exhausted = len(recent) >= window and gained == 0
    return {
        "window": len(recent),
        "marginal_yield": gained,
        "patch_exhausted": exhausted,
        "advice": ("this patch looks exhausted - 0 new pins/claims from the last "
                   f"{len(recent)} reads; try a new query or an unread cluster"
                   ) if exhausted else "patch still yielding",
    }
