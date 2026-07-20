"""Run one dataset live: keyword baseline vs foraging, plus the ordering proxy.

    python -m evals.run_eval evals/datasets/rag-survey.json --budget 25
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from foragekit import Workspace, connectors

from . import harness


def run(dataset_path: str, budget: int) -> dict:
    d = harness.load_dataset(dataset_path)
    targets = d["target_openalex_ids"]
    results: dict = {"dataset": d["name"], "budget_requests": budget,
                     "n_targets": len(targets)}

    for arm, strategy in (("keyword_baseline", "keyword"), ("foragekit", "forage")):
        ws = Workspace(tempfile.mkdtemp(prefix=f"eval-{strategy}-"))
        ws.ask(d["question"])
        connectors.reset_request_count()
        if strategy == "keyword":
            harness.discover_keyword(ws, d["question"], budget)
        else:
            harness.discover_forage(ws, d["question"], d["seed_openalex_ids"], budget)
        results[arm] = {
            "requests_used": connectors.request_count(),
            "sources_discovered": len(harness.discovered_openalex_ids(ws)),
            "recall": round(harness.recall(ws, targets), 4),
        }
        if strategy == "forage":
            results["ordering_proxy"] = harness.ordering_recall(
                ws, d["question"], targets)
    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("dataset")
    p.add_argument("--budget", type=int, default=25)
    p.add_argument("--out")
    a = p.parse_args()
    r = run(a.dataset, a.budget)
    print(json.dumps(r, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()
