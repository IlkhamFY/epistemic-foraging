"""Budget sweep across datasets: foraging recall vs. keyword-search recall.

Keyword search exhausts its query variants at ~6 requests, so its recall is a
flat line regardless of budget; foraging keeps walking the citation graph. This
sweep runs the keyword baseline once per survey and foraging at several budgets,
so the scaling gap (not a single cherry-picked budget) is what's reported.

    python -m evals.sweep                    # default datasets + budgets
    python -m evals.sweep --out results.json
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from foragekit import Workspace, connectors

from . import harness

DEFAULT_DATASETS = [
    "evals/datasets/llm-agents-survey.json",
    "evals/datasets/drug-discovery-survey.json",
    "evals/datasets/llm-hallucination-survey.json",
]
DEFAULT_BUDGETS = (25, 60, 120)


def _forage(d: dict, budget: int) -> tuple[int, int, float]:
    ws = Workspace(tempfile.mkdtemp(prefix="sweep-"))
    ws.ask(d["question"])
    connectors.reset_request_count()
    harness.discover_forage(ws, d["question"], d["seed_openalex_ids"], budget)
    return (connectors.request_count(),
            len(harness.discovered_openalex_ids(ws)),
            harness.recall(ws, d["target_openalex_ids"]))


def _keyword(d: dict) -> tuple[int, int, float]:
    ws = Workspace(tempfile.mkdtemp(prefix="sweep-kw-"))
    ws.ask(d["question"])
    connectors.reset_request_count()
    harness.discover_keyword(ws, d["question"], 999)  # runs until variants exhaust
    return (connectors.request_count(),
            len(harness.discovered_openalex_ids(ws)),
            harness.recall(ws, d["target_openalex_ids"]))


def run(datasets: list[str], budgets: tuple[int, ...]) -> dict:
    out: dict = {}
    for path in datasets:
        d = harness.load_dataset(path)
        kr = _keyword(d)
        row = {
            "n_targets": len(d["target_openalex_ids"]),
            "keyword": {"requests": kr[0], "sources": kr[1], "recall": round(kr[2], 4)},
            "forage": {},
        }
        print(f"\n=== {d['name']}  (n={row['n_targets']} targets) ===")
        print(f"  keyword (plateau): {kr[2]*100:5.1f}%  [{kr[0]} req, {kr[1]} src]")
        for b in budgets:
            fr = _forage(d, b)
            row["forage"][b] = {"requests": fr[0], "sources": fr[1],
                                "recall": round(fr[2], 4)}
            mult = (fr[2] / kr[2]) if kr[2] else float("inf")
            print(f"  forage  @{b:>3} budget: {fr[2]*100:5.1f}%  "
                  f"[{fr[0]} req, {fr[1]} src]   {mult:.0f}x keyword")
        out[d["name"]] = row
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--datasets", nargs="*", default=DEFAULT_DATASETS)
    p.add_argument("--budgets", type=int, nargs="*", default=list(DEFAULT_BUDGETS))
    p.add_argument("--out")
    a = p.parse_args()
    r = run(a.datasets, tuple(a.budgets))
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=1))
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
