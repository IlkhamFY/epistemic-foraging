"""Build a seed-reconstruction dataset from a survey's OpenAlex ID (live).

    python -m evals.make_dataset W4389071021 --name rag-survey \
        --question "Do retrieval-augmented LLMs hallucinate less than closed-book LLMs?"

Targets are the survey's OpenAlex-resolvable references (so the
connector-reachable ceiling is 100% by construction — SPEC §6.1's honest
denominator); the first two references, sorted, become the seeds and are
removed from the target set.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from foragekit.connectors import CONNECTORS


def build(survey_id: str, name: str, question: str | None) -> dict:
    recs = CONNECTORS["openalex"].lookup_many([survey_id])
    if not recs:
        raise SystemExit(f"survey {survey_id} not found on OpenAlex")
    survey = recs[0]
    refs = sorted(set(survey.referenced))
    if len(refs) < 10:
        raise SystemExit(f"survey has only {len(refs)} references - pick a bigger one")
    seeds, targets = refs[:2], refs[2:]
    return {
        "name": name,
        "question": question or f"What does the literature say about: {survey.title}?",
        "survey_openalex_id": survey_id,
        "survey_title": survey.title,
        "seed_openalex_ids": seeds,
        "target_openalex_ids": targets,
        "notes": ("targets = survey references resolvable via OpenAlex, so the "
                  "connector-reachable ceiling is 100% by construction; "
                  "seeds are the first two references (sorted) and excluded "
                  "from targets"),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("survey_openalex_id")
    p.add_argument("--name", required=True)
    p.add_argument("--question")
    p.add_argument("--out-dir", default="evals/datasets")
    a = p.parse_args()
    d = build(a.survey_openalex_id, a.name, a.question)
    out = Path(a.out_dir) / f"{a.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, indent=1))
    print(f"{out}: {len(d['target_openalex_ids'])} targets, "
          f"seeds {d['seed_openalex_ids']}")


if __name__ == "__main__":
    main()
