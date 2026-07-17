# foragekit — MVP Specification

Status: draft for review · Target: v0.1.0 · Audience: contributors and early users

foragekit is a local-first toolkit (Python library + CLI + MCP server) for
literature review and knowledge work. It gives AI agents and human researchers
three capabilities that are usually improvised: **source discovery**,
**evidence tracking**, and **uncertainty-aware note synthesis** — framed as
*epistemic foraging*: spend your reading budget where it most reduces
uncertainty about your open questions.

This document specifies the MVP. Anything not listed under Core features is
out of scope for v0.1 (see §8 for hard non-goals that are out of scope forever).

---

## 1. Core concepts and data model

A **workspace** is a directory (`.forage/` plus user-owned notes) holding
everything below. SQLite is the system of record; a JSONL ledger is the audit
log; notes are plain Markdown owned by the user.

| Entity | Fields (abridged) | Notes |
|---|---|---|
| **Question** | `id`, `text`, `status` (open/resolved), `uncertainty` (low/med/high), `created_at` | The unit of foraging. Everything is prioritized against open questions. |
| **Source** | `id`, `doi`/`arxiv_id`/`openalex_id`, `title`, `authors`, `year`, `venue`, `urls[]`, `connector`, `retrieved_at`, `read_status` (unread/skimmed/read), `text_ref` | Deduplicated across connectors by DOI, then by normalized title+year. Full text cached locally when licensing allows (arXiv, OA PDFs); otherwise abstract only. |
| **Evidence** | `id`, `source_id`, `quote` (verbatim), `locator` (page/section/char-range), `content_hash` (sha256 of quote), `retrieved_at`, `note` | A *pin*. The quote must byte-match the cached source text; pins against uncached sources are marked `unverified-locator`. |
| **Claim** | `id`, `text`, `question_ids[]`, `links[] {evidence_id, stance}`, `confidence` (0–1), `created_by` (human/agent id) | `stance ∈ {supports, contradicts, mentions}`. Status is **derived**, never hand-set: `supported` (≥1 supporting pin), `contested` (supporting and contradicting pins, or two claims linked to contradicting evidence), `unsupported` (no pins), `stale` (all pins older than a configurable window or unresolvable). |
| **Ledger entry** | `ts`, `actor`, `action`, `entity`, `payload_hash` | Append-only JSONL. Every mutation lands here; `forage log` replays it. This is what makes agent work auditable. |

Notes integration: claims can be referenced from Markdown notes with anchors
(`[[claim:c7]]`); `forage brief` and `forage audit` resolve them. Notes are
never rewritten by the tool.

## 2. Core features (v0.1)

### 2.1 Source discovery
- **Connectors (allowlist, MVP):** OpenAlex, Crossref, arXiv, Semantic Scholar.
  A connector implements `search(query) -> [SourceRecord]`,
  `lookup(id) -> SourceRecord`, `citations(id, direction) -> [SourceRecord]`.
  The base class enforces rate limits, retry/backoff, response caching, and an
  honest User-Agent with a contact address (e.g. OpenAlex "polite pool").
  **There is no generic-URL or crawler connector, and the plugin API does not
  accept one** (connectors must declare a static API host allowlist).
- **Snowballing:** forward (cited-by) and backward (references) citation
  walks from any source, bounded by depth and budget, deduplicated into the
  workspace.
- **Dedup:** DOI-first, then fuzzy title+year merge with provenance kept for
  every merged record.

### 2.2 Foraging (prioritization)
- **Frontier ranking:** `frontier(question)` scores unread sources:

  `score = w_r·relevance + w_n·novelty + w_c·centrality − w_k·cost`

  - *relevance*: BM25 (embeddings optional via `sqlite-vec`) between source
    title+abstract and the question text.
  - *novelty*: distance from the centroid of already-read sources — rewards
    reading outside the cluster you've already absorbed.
  - *centrality*: citation degree within the current snowball neighborhood.
  - *cost*: length / availability (no cached full text = higher cost).

  Weights are visible, configurable, and logged per ranking so runs are
  reproducible. The scorer is a plugin interface; the MVP scorer is a
  transparent heuristic, not a learned model.
- **Patch-leaving signal:** foraging theory's marginal-value idea, applied to
  reading: the tool tracks marginal yield (new pins + new claims per source
  read) within the current *patch* (a query or citation neighborhood) and
  surfaces "this patch looks exhausted — 0 new claims from last 4 reads;
  consider a new query or an unread cluster" in `frontier` and `status`.
  Heuristic, transparent, and advisory — it never blocks anything.

### 2.3 Evidence tracking
- Pin quotes with locators against cached source text; hash-verify on write
  and on `audit` (detects drift and link rot).
- Claims must link evidence to count as supported; stance is explicit.
- Everything an agent does is attributed in the ledger (`actor: agent:<name>`).

### 2.4 Uncertainty-aware synthesis
- `brief` compiles per-question Markdown (or JSON) reports: claims grouped by
  status, each rendered with confidence, number of *independent* sources
  (shared-author sources are counted once), stance summary, and full citation
  trail. Contested claims render both sides.
- `audit` returns machine-readable findings: unsupported claims, single-source
  claims, contested pairs, stale/unresolvable evidence, orphaned pins.
- Confidence is *stated* by the author (human or agent) but *checked* by the
  system: the eval harness (§6) measures calibration, and `audit --calibration`
  reports the workspace's historical Brier score once claims get adjudicated.

## 3. Architecture

```
┌────────────────────────── clients ──────────────────────────┐
│   forage CLI          MCP server          HTTP API (local)  │
└──────────────┬──────────────┬──────────────────┬────────────┘
               ▼              ▼                  ▼
        ┌─────────────────────────────────────────────┐
        │              foragekit core (Python)        │
        │  workspace · questions · sources · evidence │
        │  claims · frontier scorer · brief · audit   │
        ├─────────────────────────────────────────────┤
        │ connector registry (allowlist)              │
        │  openalex · crossref · arxiv · semanticschlr│
        ├─────────────────────────────────────────────┤
        │ storage: SQLite (+sqlite-vec opt.)          │
        │ ledger: append-only JSONL                   │
        │ cache: source text/PDF (licensing-aware)    │
        └─────────────────────────────────────────────┘
```

- **Language/stack:** Python ≥3.11; `typer` (CLI), `pydantic` (schemas),
  `httpx` (connectors), `mcp` (official Python SDK), `fastapi` (optional HTTP),
  SQLite via stdlib + `sqlite-vec` as an optional extra. No cloud dependency;
  no telemetry.
- **Local-first:** the workspace directory is the entire state; delete it and
  nothing remains. Syncing/sharing = git or a shared filesystem, not our server.
- **Concurrency:** single-writer SQLite with WAL; the MCP/HTTP servers serialize
  writes through the core library.

## 4. CLI surface (v0.1)

```
forage init [--workspace DIR]
forage ask "QUESTION" [--uncertainty low|med|high]
forage questions [list|resolve QID]
forage search "QUERY" [--connector NAME]... [--limit N]
forage snowball SOURCE_ID [--direction back|fwd|both] [--depth N] [--budget N]
forage sources [list|show ID] [--unread] [--question QID]
forage pin SOURCE_ID --quote TEXT --loc LOCATOR [--note TEXT]
forage claim add "TEXT" --evidence EV_ID[,EV_ID...] [--stance ...] [--confidence F] [--question QID]
forage claim link CLAIM_ID --evidence EV_ID --stance supports|contradicts|mentions
forage frontier [--question QID] [--top N] [--explain]
forage brief QID [--format md|json] [--out FILE]
forage audit [--calibration] [--format text|json]
forage status                     # workspace overview + patch-yield signal
forage log [--since TS] [--actor A]
forage export --format bibtex|csl-json [--out FILE]
forage serve [--mcp] [--http PORT]   # localhost only by default
```

Every command supports `--json` for scripting; exit codes are stable for CI use.

## 5. API surface

### 5.1 MCP tools (the agent surface)

| tool | maps to |
|---|---|
| `forage_ask(question, uncertainty?)` | register an open question |
| `forage_search(query, connectors?, limit?)` | §2.1 search |
| `forage_snowball(source_id, direction?, depth?, budget?)` | citation walk |
| `forage_get_source(source_id, with_text?)` | cached metadata/text |
| `forage_pin_evidence(source_id, quote, locator, note?)` | pin |
| `forage_add_claim(text, evidence, confidence?, questions?)` | claim |
| `forage_frontier(question_id?, top?)` | next-best reads, with `why` strings |
| `forage_brief(question_id, format?)` | compiled brief |
| `forage_audit()` | machine-readable findings |

Design rule: tools return compact structured JSON with stable ids, so an agent
can chain them without re-parsing prose. All writes are attributed
(`actor: agent:<client name>`) in the ledger.

### 5.2 Python API

```python
from foragekit import Workspace

ws = Workspace.open("./review")
q = ws.ask("Do RAG systems hallucinate less than closed-book LLMs?")
ws.search("retrieval augmented generation hallucination", connectors=["openalex"])
for s in ws.frontier(q, top=5): ...
ev = ws.pin(source_id, quote="...", locator="§5.2")
ws.claim("RAG reduces but does not eliminate hallucination",
         evidence=[ev.id], confidence=0.8, questions=[q.id])
print(ws.brief(q).to_markdown())
```

### 5.3 HTTP API (optional, off by default)
`forage serve --http` exposes the same operations as JSON endpoints on
localhost for non-Python integrations. No auth story in v0.1 beyond
localhost-binding; do not deploy publicly.

## 6. Evaluation metrics

The eval harness (`evals/`) ships with the repo and runs in CI on small fixtures;
full runs are manual. Five metric families:

1. **Discovery recall — seed reconstruction.** Take published systematic
   reviews/surveys with explicit included-studies lists; give the harness the
   research question plus 2 seed papers; measure **recall@budget** of the
   included studies after N connector calls, vs. a keyword-search-only baseline.
   Report queries-to-50%-coverage.
2. **Evidence integrity.** (a) *Quote fidelity*: 100% of pins byte-match cached
   text — automated, a release gate. (b) *Citation-support rate*: on a sampled
   set, does the pinned quote actually entail the claim? Scored by human
   annotation, optionally pre-screened by an LLM judge that is itself
   calibrated against the human sample. (c) *Provenance completeness*: % of
   claims in a compiled brief with ≥1 resolvable pin (target: 100% by
   construction).
3. **Calibration.** Brier score and expected calibration error of claim
   confidences against adjudicated ground truth on a labeled claim set
   (built once during Phase "review", reused after).
4. **Foraging efficiency.** New-pins-per-read and new-claims-per-read when
   reading in `frontier` order vs. relevance-only order vs. random, on the
   seed-reconstruction tasks; plus **redundancy rate** (reads yielding nothing
   new). This is the metric that justifies the "foraging" framing — if frontier
   ordering doesn't beat relevance ordering, the feature fails its gate.
5. **Agent integration.** Scripted end-to-end tasks ("produce a brief on X with
   ≥15 supported claims") run by an MCP-connected agent with and without
   foragekit tools: task success, wall-clock, tokens, and audit findings on the
   result.

## 7. Distribution & OSS posture

- PyPI package `foragekit`, CLI entry point `forage`. Apache-2.0.
- `CONTRIBUTING.md`, code of conduct, issue/PR templates, `SECURITY.md`,
  good-first-issue labels from day one. Connectors are the designed
  first-contribution surface (small, well-bounded, high demand).
- Semantic versioning; `0.x` may break APIs with changelog notice.

## 8. Non-goals (permanent, enforced in design)

1. **No offensive security / OSINT.** No person-centric entity resolution, no
   dossier building, no recon features. Sources are documents, not people.
2. **No biosafety workflows.** No lab-protocol planning or wet-lab integration.
3. **No persuasion systems.** No audience modeling, targeting, or message
   optimization. Briefs are for the asker's understanding, not for moving
   third parties.
4. **No covert collection.** Connector allowlist only; no generic crawler, no
   headless browser, no credentialed scraping, no proxy rotation, no
   captcha-solving — and the plugin interface is designed so these cannot be
   added without forking (static host allowlist, no raw-request escape hatch).

PRs that add capabilities in these categories are closed with a pointer to
this section.
