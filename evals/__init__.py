"""foragekit evaluation harness (PLAN milestone M-E).

Seed-reconstruction benchmark per SPEC §6.1: hide a survey's bibliography,
start from the research question plus two seed papers, and measure
recall@budget of the hidden references — foraging (search + snowball)
vs. a keyword-search-only baseline — plus the SPEC §6.4 ordering proxy
(frontier vs. relevance-only reading order over the same discovered pool).

Offline metric math is unit-tested in CI; live runs are manual:

    python -m evals.make_dataset W4389071021 --name rag-survey
    python -m evals.run_eval evals/datasets/rag-survey.json --budget 25
"""
