# foragekit — Implementation Plan

Assumes a team of 2–3 engineers (one comfortable with information-retrieval
plumbing, one strong on developer experience), ~16 weeks to a public v0.1.0.
Phases are gated: each ends with a concrete artifact and an explicit go/no-go.

---

## Phase 1 — Plan (weeks 1–2)

Goal: make sure we're building the right narrow thing before freezing contracts.

- Interview 8–10 target users: agent builders doing research automation, PhD
  students/postdocs running literature reviews, research engineers. Focus on
  where their current loop breaks (discovery? provenance? synthesis?) and what
  they'd adopt incrementally.
- Pick the evaluation datasets **now**, not after implementation: 5–10
  published systematic reviews/surveys with explicit included-studies lists for
  the seed-reconstruction benchmark (SPEC §6.1), spanning at least CS and one
  non-CS field.
- Validate connector viability: rate limits, ToS, id coverage, and overlap for
  OpenAlex, Crossref, arXiv, Semantic Scholar. Confirm the licensing rules for
  local full-text caching per source type.
- Write ADRs for the three riskiest decisions: storage (SQLite as system of
  record + JSONL ledger), frontier scoring (transparent heuristic vs. learned),
  and MCP-first vs. HTTP-first agent surface.
- Risk register: connector API instability, PDF text extraction quality,
  frontier ranking failing to beat relevance baseline (this one has a kill
  criterion attached — see Phase 4).

**Exit artifact:** 2-page findings memo + chosen benchmarks + ADRs.
**Go/no-go:** at least 5 interviewees say they'd try the MVP loop as described.

## Phase 2 — Spec (weeks 3–4)

Goal: freeze the contracts so implementation can parallelize.

- JSON Schemas for all entities (Question, Source, Evidence, Claim, Ledger
  entry) and for every MCP tool's input/output. These are the API — reviewed
  line by line.
- Connector interface contract + conformance test suite that any connector
  (including future community ones) must pass, including the static host
  allowlist and polite-client requirements.
- CLI surface review: every command's flags, JSON output shape, and exit codes
  (SPEC §4) — checked against three written user journeys (solo researcher,
  agent via MCP, CI audit bot).
- Eval harness design doc: dataset format, metric definitions, baseline
  implementations, and what runs in CI vs. manually.
- Guardrails policy: translate SPEC §8 into enforceable review rules
  (CONTRIBUTING section + PR checklist + connector conformance tests).

**Exit artifact:** frozen schemas + interface docs merged; tracking issues cut
for every Phase 3 milestone.
**Go/no-go:** two team members independently walk the three user journeys
against the spec without finding a missing operation.

## Phase 3 — Implement (weeks 5–12)

Milestones are vertical slices — each ships something usable and demo-able.
Eval harness is built alongside, not at the end.

| Milestone | Weeks | Scope | Demo |
|---|---|---|---|
| **M1 — Workspace core** | 5–6 | `init`, questions, SQLite store, ledger, `status`, `log` | create workspace, ask questions, audit trail replays |
| **M2 — Discovery** | 6–8 | OpenAlex + arXiv connectors, `search`, dedup, `snowball`, Crossref + S2 | reconstruct 30% of a survey's bibliography from 2 seeds |
| **M3 — Evidence** | 8–9 | text cache, `pin` with hash verification, claims + stances, `audit` | pin quotes, break one on purpose, `audit` catches it |
| **M4 — Foraging & synthesis** | 9–11 | frontier scorer + `--explain`, patch-yield signal, `brief`, `export` | frontier-ordered reading measurably beats relevance order on one benchmark |
| **M5 — Agent surface** | 11–12 | MCP server, tool schemas, attribution in ledger; optional HTTP | a Claude agent runs ask→search→pin→claim→brief end-to-end, human replays the ledger |

Engineering ground rules: trunk-based with PR review; CI runs unit tests,
connector conformance (against recorded fixtures, not live APIs), lint/type
checks, and the small-fixture eval suite; every milestone updates docs in the
same PR.

**Exit artifact:** v0.1.0-rc, installable via `pip`, all five milestones demo-able.

## Phase 4 — Review (weeks 13–16)

Goal: prove it works, prove it's safe to open, then open it.

- **Eval week:** run the full SPEC §6 suite. Gates: quote fidelity 100%;
  frontier ordering beats relevance-only on foraging efficiency on the majority
  of benchmarks (if it doesn't, ship v0.1 with frontier marked experimental and
  say so — kill criterion honored, no silent shipping of a broken headline
  feature); citation-support rate ≥95% on the audited sample.
- **External review:** 3–5 interviewees from Phase 1 run a real review with it
  for a week; fix the top usability findings.
- **Code & safety review:** dependency audit, license header check,
  `SECURITY.md`, and a specific pass verifying the SPEC §8 non-goals hold
  (no raw-request escape hatch in connectors, localhost-only default for
  `serve`, honest User-Agent everywhere).
- **Launch checklist:** README quickstart tested on clean machines (Linux/mac),
  API docs generated from schemas, CONTRIBUTING + templates + ~10 curated
  good-first-issues (mostly connectors and brief formats), tagged v0.1.0 on
  PyPI, announcement post explaining the epistemic-foraging framing and the
  eval results — including the negative ones.

**Exit artifact:** public v0.1.0 + published eval results.

## Post-v0.1 candidates (explicitly deferred)

Embedding-based relevance by default · PubMed/CORE connectors (community) ·
claim adjudication workflows for calibration tracking · multi-workspace merge
(team reviews) · learned frontier scorer trained on the logged features ·
Zotero/Obsidian bridges.
