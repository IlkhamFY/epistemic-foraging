# foragekit — Implementation Plan

Assumes a team of 2–3 engineers (one comfortable with information-retrieval
plumbing, one strong on developer experience), **~18 weeks to a public v0.1.0**.
Phases are gated: each ends with a concrete artifact and an explicit go/no-go.

Two lessons are baked into the schedule up front rather than discovered in
week 10: **PDF text extraction is a real subsystem, not a line item** (the
evidence model sits on top of it), and **the eval harness is on the critical
path from the first discovery demo onward** (so it has an owner and dates).

---

## Phase 1 — Plan (weeks 1–2)

Goal: make sure we're building the right narrow thing before freezing contracts.

- Interview 8–10 target users: agent builders doing research automation, PhD
  students/postdocs running literature reviews, research engineers. Focus on
  where their current loop breaks (discovery? provenance? synthesis?) and what
  they'd adopt incrementally.
- **Extraction spike (de-risks the evidence model):** prototype PDF
  extraction + canonicalization on ~50 real arXiv PDFs; draft the
  canonicalization ADR (extractor library choice; Unicode NFC, ligature
  expansion, dehyphenation, whitespace folding; pipeline versioning). If
  canonical-match verification can't hit near-100% on honest quotes here, the
  evidence model changes now, not in week 10.
- Pick the evaluation datasets **now**: 5–10 published systematic
  reviews/surveys with explicit included-studies lists for the
  seed-reconstruction benchmark (SPEC §6.1), spanning at least CS and one
  non-CS field. For each, resolve included studies to DOIs (budgeted grunt
  work, not an afterthought) and measure the **connector-reachable ceiling**
  so recall is reported against an honest denominator.
- Validate connector viability: rate limits, ToS, id coverage, and overlap for
  OpenAlex, Crossref, arXiv, Semantic Scholar. **Apply for the Semantic
  Scholar API key now** (approval has lead time; snowballing needs it) and
  write the no-key fallback plan. Confirm licensing rules for local full-text
  caching per source type, and draft the curated OA host registry.
- Write ADRs for the riskiest decisions: storage (SQLite as system of record +
  hash-chained JSONL ledger), extraction/canonicalization (from the spike),
  frontier scoring (TF-IDF default for novelty; embeddings optional), and the
  MCP-only v0.1 surface (HTTP deferred).
- Risk register: connector API instability, extraction quality on non-arXiv
  PDFs, frontier ranking failing to beat the relevance baseline (kill
  criterion attached — see Phase 4), S2 key delay, benchmark reachability
  ceilings too low to be meaningful.

**Exit artifact:** 2-page findings memo + chosen benchmarks with reachability
ceilings + ADRs (including the extraction spike results).
**Go/no-go:** at least 5 interviewees say they'd try the MVP loop as described,
AND the extraction spike sustains canonical-match verification on real PDFs.

## Phase 2 — Spec (weeks 3–4)

Goal: freeze the contracts so implementation can parallelize.

- JSON Schemas for all entities (Question, Source, Evidence, Claim, Ledger
  entry — including verification tiers, `text_status`, `extractor_version`,
  hash chaining) and for every MCP tool's input/output. These are the API —
  reviewed line by line. The MCP contract must include the loop-closers:
  list/get tools for session resume, `forage_find_text` quote-snap,
  `forage_mark_read`, stance-bearing claim links, windowed text access.
- Connector interface contract + conformance test suite that any connector
  (including future community ones) must pass: politeness, static host
  declaration, registry validation, works-and-citations-only surface.
- Dedup design: DOI-first, preprint↔published linking via OpenAlex relations,
  blocked fuzzy title+year matching (no O(n²) scans).
- CLI surface review: every command's flags, JSON output shape, and exit codes
  (SPEC §4) — checked against three written user journeys (solo researcher,
  agent via MCP, CI audit bot).
- Eval harness design doc: dataset format, metric definitions per SPEC §6
  (which are gated vs. report-only), baseline implementations, what runs in CI
  vs. manually — and the **scripted-agent reader** for the foraging-efficiency
  study: define and cost it (papers × orderings × benchmarks) here.
- Guardrails policy: translate SPEC §8 into enforceable review rules
  (CONTRIBUTING section + PR checklist + connector conformance tests +
  OA-registry acceptance criteria).

**Exit artifact:** frozen schemas + interface docs merged; tracking issues cut
for every Phase 3 milestone.
**Go/no-go:** two team members independently walk the three user journeys
against the spec without finding a missing operation — the agent-via-MCP
journey must close the full loop, including session resume.

## Phase 3 — Implement (weeks 5–14)

Milestones are vertical slices — each ships something usable and demo-able.
The eval harness is a milestone with an owner, not a background wish; M2 and
M5 demos depend on it existing first.

| Milestone | Weeks | Scope | Demo |
|---|---|---|---|
| **M1 — Workspace core** | 5–6 | `init`, questions, SQLite store, hash-chained ledger, `status`, `log --verify` | create workspace, ask questions, tamper with the ledger, verification catches it |
| **M-E — Eval harness** *(owned by one engineer, runs alongside)* | 6–9 | dataset loaders, recall@budget + baselines, CI fixture runs | harness scores a keyword-only baseline on one benchmark before M2's demo needs it |
| **M-A — MCP walking skeleton** *(runs alongside — adoption is the point, so agents never wait for M6)* | 6–14 | stdio server up in week 6 exposing whatever tools exist; each milestone adds its tools the week they land; `uvx foragekit` entry point; workspace auto-init on first tool call | an agent gets useful results from week-6 foragekit (ask + search + list) the same week M2 lands |
| **M2 — Discovery** | 6–9 | OpenAlex + arXiv connectors, `search`, dedup (DOI + preprint-linking + blocked fuzzy), `snowball`; Crossref + S2 land here if the key arrived, else fast-follow | reconstruct 30% of a survey's reachable bibliography from 2 seeds, measured by M-E |
| **M3 — Text pipeline** | 9–10 | OA-registry fetch, extraction + canonicalization (from the Phase 1 ADR), versioned cache, `fetch-text`, `text --find` | cache an arXiv paper, quote-snap an approximate quote to an exact span |
| **M4 — Evidence** | 10–11 | `pin` with canonical-match verification + tiers, claims with stances, `claim link`, `audit` (incl. `--refetch`) | pin quotes, break one on purpose, `audit` catches it and labels tiers |
| **M5 — Foraging & synthesis** | 11–13 | frontier scorer + `--explain`, patch-yield signal, `brief`, `export`; foraging-trace collection starts | frontier ordering beats relevance ordering on one benchmark (proxy gate, via M-E) |
| **M6 — Agent surface complete** | 13–14 | close M-A: full tool set audit against SPEC §5.1, `agents/SKILL.md` finalized against the real tools, shareable-brief footer, attribution polish | a Claude agent given only SKILL.md runs the loop end-to-end — including resuming a day-old workspace — and a human replays the ledger |

Engineering ground rules: trunk-based with PR review; CI runs unit tests,
connector conformance (against recorded fixtures, not live APIs), lint/type
checks, and the small-fixture eval suite; every milestone updates docs in the
same PR.

**Exit artifact:** v0.1.0-rc, installable via `pip`, all milestones demo-able.

## Phase 4 — Review (weeks 15–18)

Goal: prove it works, prove it's safe to open, then open it.

- **Eval week:** run the full SPEC §6 suite. Gates (matching SPEC §6 exactly):
  discovery gate — recall@budget beats the keyword-search-only baseline on the
  majority of benchmarks (§6.1); quote fidelity 100% canonical-match on
  `verified-*` pins; citation-support rate ≥95% on the annotation set
  pre-built from M4–M5 dogfooding pins; frontier proxy gate — frontier
  ordering beats relevance-only on recall@budget on the majority of
  benchmarks, else frontier ships marked *experimental* and the release notes
  say so (kill criterion honored, no silent shipping of a broken headline
  feature). Verification-tier shares and the agent-integration
  results (§6.5) are published as report-only numbers. Calibration is deferred
  (§6.3) and the release notes say confidence is author-stated.
- **External review:** 3–5 interviewees from Phase 1 run a real review with it
  for a week; fix the top usability findings.
- **Code & safety review:** dependency audit, license header check,
  `SECURITY.md`, and a specific pass verifying the SPEC §8 commitments hold as
  specified: connector registry validation + override flag behavior, OA-registry
  fetch path (no generic-URL fetch reachable from any surface), stdio-only MCP
  with no network listener, ledger hash-chain verification, honest User-Agent
  on every connector.
- **Launch checklist:** README quickstart tested on clean machines (Linux/mac)
  — including the `claude mcp add forage -- uvx foragekit serve --mcp`
  one-liner from a machine that has never seen the package; API docs generated
  from schemas; a 2-minute recorded demo (asciinema/GIF in the README) of an
  agent foraging a real question end-to-end; an example brief artifact linked
  from the README so the "receipts" are visible before anyone installs
  anything; MCP registry and directory listings submitted; CONTRIBUTING +
  templates + ~10 curated good-first-issues (mostly connectors and brief
  formats); tagged v0.1.0 on PyPI; announcement post explaining the
  epistemic-foraging framing and the eval results — including the negative
  ones.

**Exit artifact:** public v0.1.0 + published eval results.

## The adoption loop (why this spreads)

Three reinforcing mechanisms, all designed-in rather than bolted on at launch:

1. **The brief is the marketing.** Every compiled brief is self-contained,
   shows verification tiers and receipts inline, and carries a one-line
   attribution footer (removable — goodwill matters more than impressions).
   People share research artifacts constantly; a brief that visibly proves its
   claims is the demo, and the footer is the link back.
2. **Install friction is one line.** `uvx foragekit serve --mcp` + workspace
   auto-init means the gap between "saw a shared brief" and "my agent produced
   one" is a single command. `agents/SKILL.md` removes the prompting friction
   the same way the one-liner removes the install friction.
3. **Agents are users from week 6.** The M-A walking skeleton means the MCP
   surface hardens against real agent traffic for eight weeks before launch,
   and early adopters become the launch amplifiers — with connectors as the
   designed first contribution when they want more sources.

## Post-v0.1 candidates (explicitly deferred)

Calibration measurement + claim-adjudication workflow (§6.3) · HTTP API with
per-workspace bearer token and Origin/Host validation (SPEC §5.3) · the full
reading-order foraging study as a publishable result · embedding-based
relevance by default · PubMed/CORE connectors (community) · LLM-judge
pre-screening for citation support (calibrated against the human sample) ·
multi-workspace merge (team reviews) · learned frontier scorer trained on the
logged features · Zotero/Obsidian bridges.
