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
everything below. SQLite is the system of record; a hash-chained JSONL ledger
is the audit log; notes are plain Markdown owned by the user.

| Entity | Fields (abridged) | Notes |
|---|---|---|
| **Question** | `id`, `text`, `status` (open/resolved), `uncertainty` (low/med/high), `created_at` | The unit of foraging. Everything is prioritized against open questions. |
| **Source** | `id`, `doi`/`arxiv_id`/`openalex_id`, `title`, `authors`, `year`, `venue`, `urls[]`, `connector`, `retrieved_at`, `read_status` (unread/skimmed/read), `text_ref`, `text_status` (cached-full/abstract-only/uncachable), `extractor_version` | Deduplicated across connectors by DOI, then preprint↔published linking (OpenAlex relations), then blocked fuzzy title+year merge (candidate blocking, not O(n²)). Full text cached only from the curated OA host registry (§2.1); otherwise abstract only, and `text_status` says so. |
| **Evidence** | `id`, `source_id`, `quote` (verbatim canonical text), `locator` (page/section/char-range), `content_hash` (sha256 of canonical quote), `verification` (verified-full-text / verified-abstract / unverified-locator), `extractor_version`, `retrieved_at`, `note` | A *pin*. The quote must **canonical-match** (§2.3) the cached text; when only the abstract is cached the pin is `verified-abstract`; with no cached text it is `unverified-locator`. Verification tier is carried into every brief and audit. |
| **Claim** | `id`, `text`, `question_ids[]`, `links[] {evidence_id, stance}`, `confidence` (0–1, author-stated), `created_by` (human/agent id) | `stance ∈ {supports, contradicts, mentions}`. Status is **derived**, never hand-set, and the rules are total: `contested` (≥1 contradicting pin), `supported` (≥1 supporting pin, none contradicting), `unsupported` (no supporting or contradicting pins — `mentions` links don't count), plus the `stale` overlay (all pins older than a configurable window). In v0.1 confidence is author-stated and unvalidated — calibration measurement is explicitly deferred (§6.3). |
| **Ledger entry** | `ts`, `actor`, `action`, `entity`, `payload_hash`, `prev_hash` | Append-only JSONL, hash-chained: each entry commits to its predecessor, and `forage log --verify` checks the chain. Actor names are client-asserted; the ledger assumes a non-adversarial local machine — it is tamper-*evident* against accidental edits and honest-client confusion, not a defense against a hostile local process. |

Notes integration: claims can be referenced from Markdown notes with anchors
(`[[claim:c7]]`); `forage brief` and `forage audit` resolve them. Notes are
never rewritten by the tool.

## 2. Core features (v0.1)

### 2.1 Source discovery
- **Connectors (allowlist, MVP):** OpenAlex and arXiv (core); Crossref and
  Semantic Scholar (fast-follow — targeted within the same milestone but
  allowed to slip behind it, because S2's usable rate limits require an API
  key whose acquisition is a Phase 1 task).
  A connector implements `search(query) -> [SourceRecord]`,
  `lookup(id) -> SourceRecord`, `citations(id, direction) -> [SourceRecord]`.
  The base class enforces rate limits, retry/backoff, response caching, and an
  honest User-Agent with a contact address (e.g. OpenAlex "polite pool").
  The connector contract covers **works and citations only** — author-entity
  endpoints are not part of the interface (§8).
- **Connector registration:** every connector declares a static API host list.
  At registration, hosts are validated against a curated scholarly-API registry
  shipped with foragekit; a connector whose hosts are not in the registry loads
  only with an explicit per-workspace user override
  (`forage connectors enable NAME --allow-unlisted-host`). This is
  enforceable for conforming plugins;
  arbitrary locally-installed Python can always do arbitrary things (§8 is
  honest about this).
- **Full-text retrieval:** `fetch-text` retrieves and caches full text **only**
  from the curated OA host registry (arXiv, PubMed Central OA, DOI-resolved
  locations whose host is in the registry). There is no generic-URL fetcher:
  a `urls[]` entry on a host outside the registry is stored as metadata but
  never fetched, and the source stays `abstract-only`. Fetch results report
  cache status and the licensing/host reason on failure, so callers can
  distinguish "can't cache" from "haven't cached".
- **Snowballing:** forward (cited-by) and backward (references) citation
  walks from any source, bounded by depth and budget, deduplicated into the
  workspace.

### 2.2 Foraging (prioritization)
- **Frontier ranking:** `frontier(question)` scores unread sources:

  `score = w_r·relevance + w_n·novelty + w_c·centrality − w_k·cost`

  - *relevance*: BM25 between source title+abstract and the question text.
  - *novelty*: cosine distance between the source's **TF-IDF vector** (over the
    workspace corpus, title+abstract) and the centroid of already-read sources.
    TF-IDF is the required default so the formula is buildable with zero
    optional dependencies; embeddings via `sqlite-vec` are an optional upgrade
    for both relevance and novelty.
  - *centrality*: citation degree within the current snowball neighborhood.
  - *cost*: length / availability (no cached full text = higher cost).

  Weights are visible, configurable, and logged per ranking so runs are
  reproducible. The scorer is a plugin interface; the MVP scorer is a
  transparent heuristic, not a learned model.
- **Read events (defined semantics):** `read_status` advances only via an
  explicit mark (`forage sources mark`, `forage_mark_read`) — plus one
  automatic rule: retrieving a text window (`forage_get_source_text`) advances
  `unread → skimmed`. Patch-yield counts pins + claims per source marked
  skimmed/read, so the signal means the same thing for humans and agents.
- **Patch-leaving signal:** foraging theory's marginal-value idea, applied to
  reading: the tool tracks marginal yield (new pins + new claims per source
  read) within the current *patch* (a query or citation neighborhood) and
  surfaces "this patch looks exhausted — 0 new claims from last 4 reads;
  consider a new query or an unread cluster" in `frontier` output
  (`patch_exhausted` field), `status`, and `forage_status`. Heuristic,
  transparent, and advisory — it never blocks anything.

### 2.3 Evidence tracking
- **Canonicalization, not byte-match.** Real PDF extraction produces ligatures,
  hyphenation breaks, and reflowed whitespace, so raw byte-matching would fail
  on honest quotes. All cached text and all quotes are normalized under a
  documented, versioned canonicalization policy (Unicode NFC, ligature
  expansion, dehyphenation across line breaks, whitespace folding), and
  verification means **the canonical quote occurs in the canonical cached
  text**. The extraction+canonicalization pipeline is versioned; every cache
  entry and pin records its `extractor_version`, so an extractor upgrade
  triggers re-verification of old pins rather than mass invalidation.
- **Quote-snap.** Agents and humans rarely have byte-exact text. `find_text`
  (CLI: `forage text ID --find "approximate text"`; MCP: `forage_find_text`)
  searches the canonical cached text and returns exact spans + locators,
  pin-ready. `forage pin --find` uses it directly.
- **Verification split, honestly labeled.** *Local verification* (on write and
  on `audit`) checks pins against the local cache — it catches workspace
  corruption and extractor drift, nothing more. *Upstream re-resolution*
  (`audit --refetch`, explicitly best-effort) re-fetches from the OA registry
  and re-verifies under canonicalization, which is what actually detects link
  rot and upstream drift. The docs and output never conflate the two.
- Claims must link evidence to count as supported; stance is explicit.
- Everything an agent does is attributed in the hash-chained ledger
  (`actor: agent:<name>`, client-asserted).

### 2.4 Uncertainty-aware synthesis
- `brief` compiles per-question Markdown (or JSON) reports: claims grouped by
  derived status (supported / contested / unsupported / stale), each rendered
  with author-stated confidence, verification tier of its pins, number of
  *independent* sources, stance summary, and full citation trail. Contested
  claims render both sides.
- **Independence heuristic (deliberately narrow):** within a single brief,
  sources sharing any OpenAlex author ID (or, for unresolved sources, an exact
  normalized author string) are counted once. Computed per-brief and never
  persisted — foragekit builds no author-entity table, keeps no cross-workspace
  author graph, and the connector contract excludes author-entity endpoints.
  Coverage caveat: sources that don't resolve to OpenAlex fall back to string
  matching, which under- and over-merges on common names; the brief footnotes
  which method applied.
- **Briefs are shareable artifacts (the adoption loop).** Compiled briefs are
  self-contained Markdown: provenance footnotes inline, verification tiers
  visible, readable with no workspace and no foragekit install. A one-line
  attribution footer ("foraged with foragekit · N claims, every one pinned")
  is on by default and removable (`--no-badge`, or `brief.badge = false` in
  workspace config). The shared brief is the product's proof and its primary
  distribution channel: every claim shows its receipts.
- `audit` returns machine-readable findings: unsupported claims, single-source
  claims, contested pairs, stale evidence, unverified/degraded pins, orphaned
  pins.
- **Confidence in v0.1 is author-stated and unvalidated, and briefs say so.**
  Calibration measurement (Brier/ECE against adjudicated claims) requires an
  adjudication workflow that is deferred post-v0.1 (§6.3); no `--calibration`
  flag ships in v0.1.

## 3. Architecture

```
┌──────────────────── clients (v0.1) ─────────────────────┐
│      forage CLI              MCP server (stdio)         │
└──────────────┬─────────────────────┬────────────────────┘
               ▼                     ▼
        ┌─────────────────────────────────────────────┐
        │              foragekit core (Python)        │
        │  workspace · questions · sources · evidence │
        │  claims · frontier scorer · brief · audit   │
        ├─────────────────────────────────────────────┤
        │ connector registry (validated allowlist)    │
        │  openalex · arxiv · crossref · semanticschlr│
        ├─────────────────────────────────────────────┤
        │ text pipeline: OA-registry fetch → extract  │
        │   → canonicalize (versioned)                │
        ├─────────────────────────────────────────────┤
        │ storage: SQLite (+sqlite-vec opt.)          │
        │ ledger: hash-chained append-only JSONL      │
        └─────────────────────────────────────────────┘
```

- **Language/stack:** Python ≥3.11; `typer` (CLI), `pydantic` (schemas),
  `httpx` (connectors), `mcp` (official Python SDK, stdio transport),
  SQLite via stdlib + `sqlite-vec` as an optional extra. No cloud dependency;
  no telemetry.
- **Local-first:** the workspace directory is the entire state; delete it and
  nothing remains. Syncing/sharing = git or a shared filesystem, not our server.
- **No network listener in v0.1.** The MCP server speaks stdio to a local
  client. An HTTP API is deferred post-v0.1 because shipping one responsibly
  requires an auth design (per-workspace bearer token, Origin/Host validation
  against DNS rebinding) that v0.1 will not rush.
- **Concurrency:** single-writer SQLite with WAL; the MCP server serializes
  writes through the core library.

## 4. CLI surface (v0.1)

```
forage init [--workspace DIR]
forage ask "QUESTION" [--uncertainty low|med|high]
forage questions [list|resolve QID]
forage connectors [list|enable NAME [--allow-unlisted-host]]
forage search "QUERY" [--connector NAME]... [--limit N]
forage snowball SOURCE_ID [--direction back|fwd|both] [--depth N] [--budget N]
forage sources [list|show ID] [--unread] [--question QID]
forage sources mark ID --status skimmed|read
forage fetch-text SOURCE_ID                  # cache full text (OA registry only)
forage text SOURCE_ID [--find "APPROX TEXT"] [--window START:CHARS]
forage pin SOURCE_ID (--quote TEXT | --find "APPROX TEXT") --loc LOCATOR [--note TEXT]
forage claim add "TEXT" [--evidence EV_ID[:STANCE],...] [--confidence F] [--question QID]
forage claim link CLAIM_ID --evidence EV_ID --stance supports|contradicts|mentions
forage frontier [--question QID] [--top N] [--explain]
forage brief QID [--format md|json] [--out FILE] [--no-badge]
forage audit [--refetch] [--format text|json]
forage status                     # workspace overview + patch-yield signal
forage log [--since TS] [--actor A] [--verify]
forage export --format bibtex|csl-json [--out FILE]
forage serve --mcp                # stdio MCP server
```

Every command supports `--json` for scripting; exit codes are stable for CI use.

## 5. API surface

### 5.1 MCP tools (the agent surface)

The full loop — ask → search → snowball → fetch/read → pin → claim → brief →
audit — is closable by an MCP-only agent, including resuming an existing
workspace in a fresh session. `export` is deliberately human-only.

Friction is a design requirement: the server starts with `uvx foragekit serve
--mcp` (zero install, zero config) and **auto-initializes a workspace on the
first tool call** (in the current directory, or a configured path), so an
agent's first useful result requires no human setup step. The repo ships
[`agents/SKILL.md`](../agents/SKILL.md), a drop-in instruction file teaching
any agent to run the loop well.

**The server teaches the agent.** A condensed version of the loop ships in
the MCP `initialize` response's `instructions` field (clients inject it into
the model's context automatically), and every tool response carries a
one-line `next` hint (`forage_search` → "rank reads with forage_frontier";
`forage_pin_evidence` → "cite this id in forage_add_claim"), so a cold agent
follows the loop with zero prompting — and keeps following it after the
handshake has scrolled out of attention. The CLI prints the same hints in
human mode; `--json` output stays pure data.

| tool | purpose |
|---|---|
| `forage_ask(question, uncertainty?)` | register an open question |
| `forage_list_questions()` | ids, text, status, uncertainty — session resume starts here |
| `forage_update_question(question_id, status?, uncertainty?, note?)` | resolve or re-grade a question |
| `forage_search(query, connectors?, limit?)` | §2.1 search |
| `forage_snowball(source_id, direction?, depth?, budget?)` | citation walk |
| `forage_list_sources(filter?, question_id?, read_status?, limit?, cursor?)` | paginated compact rows (id, title, year, read_status, text_status) |
| `forage_get_source(source_id)` | full metadata for one source (no text) |
| `forage_fetch_text(source_id)` | attempt OA-registry text caching; returns cache status + reason |
| `forage_get_source_text(source_id, start?, max_chars?)` | windowed canonical text + locator metadata; auto-advances unread→skimmed |
| `forage_find_text(source_id, query)` | quote-snap: exact canonical spans + locators, pin-ready |
| `forage_mark_read(source_id, status)` | skimmed / read |
| `forage_pin_evidence(source_id, quote, locator, note?)` | pin (canonical-match verified) |
| `forage_add_claim(text, evidence?: [{evidence_id, stance}], confidence?, questions?)` | claim with explicit stances; evidence optional (a no-evidence claim is born `unsupported`) |
| `forage_link_evidence(claim_id, evidence_id, stance)` | attach later-found (incl. contradicting) evidence |
| `forage_get_claim(claim_id)` / `forage_get_evidence(evidence_id)` | remediation lookups (e.g. after audit flags c7 ↔ c11) |
| `forage_frontier(question_id?, top?)` | next-best reads with `why` strings and `patch_exhausted` signal |
| `forage_status()` | workspace overview + per-patch marginal yield |
| `forage_brief(question_id, format?, out_path?)` | with `out_path`: writes file, returns `{path, claim_counts_by_status, audit_summary}` instead of the full document |
| `forage_audit(refetch?)` | machine-readable findings; `refetch` triggers best-effort upstream re-resolution (§2.3) |
| `forage_log(since?, actor?, limit?)` | recent ledger entries — attribution self-check and post-compaction recovery |

Design rules: tools return compact structured JSON with stable ids; list tools
paginate; bulk operations return `{added, merged, source_ids, top_by_centrality:
[{id, title, year}, …]}` rather than full records; nothing returns a whole
paper in one call. All writes are attributed (`actor: agent:<client name>`)
in the ledger.

### 5.2 Python API

```python
from foragekit import Workspace

ws = Workspace.open("./review")
q = ws.ask("Do RAG systems hallucinate less than closed-book LLMs?")
ws.search("retrieval augmented generation hallucination", connectors=["openalex"])
for s in ws.frontier(q, top=5): ...
span = ws.find_text(source_id, "hallucination rates dropped")
ev = ws.pin(source_id, quote=span.text, locator=span.locator)
ws.claim("RAG reduces but does not eliminate hallucination",
         evidence=[(ev.id, "supports")], confidence=0.8, questions=[q.id])
print(ws.brief(q).to_markdown())
```

### 5.3 HTTP API — deferred post-v0.1
Deliberately absent from v0.1 (see §3): a network-reachable unauthenticated
write surface is a CSRF/DNS-rebinding hazard even bound to localhost. When it
lands it will require a per-workspace bearer token and Origin/Host validation
from day one.

## 6. Evaluation metrics

The eval harness (`evals/`) ships with the repo, is owned as its own milestone
(PLAN M-E), runs on small fixtures in CI, and in full manually. **Gated**
metrics block release; **report-only** metrics are published with the release
notes either way.

### 6.1 Discovery recall — seed reconstruction *(gated)*
Take published systematic reviews/surveys with explicit included-studies lists;
give the harness the research question plus 2 seed papers; measure
**recall@budget** of the included studies after N connector calls, vs. a
keyword-search-only baseline. Because non-CS reviews include studies reachable
only via Embase/Scopus/hand-search, Phase 1 measures each benchmark's
**connector-reachable ceiling**, and recall is reported as a fraction of
reachable studies. Report queries-to-50%-coverage. **Gate:** foragekit's
recall@budget beats the keyword-search-only baseline on the majority of
benchmarks.

### 6.2 Evidence integrity *(gated)*
(a) *Quote fidelity*: 100% of `verified-*` pins must canonical-match cached
text — automated, a release gate. (b) *Citation-support rate*: ≥95% on an
audited sample — does the pinned quote actually entail the claim? Scored by
human annotation on a set pre-built from the team's own dogfooding pins during
M4–M5 (not started in review week). No LLM judge in v0.1. (c) *Provenance
completeness*: the share of claims in a compiled brief with ≥1 supporting pin
(unsupported claims do appear in briefs, loudly flagged, so this is a real
number — not a vacuous 100%), alongside the **share of pins per verification
tier** (verified-full-text / verified-abstract / unverified-locator). Together
these tell a reader how solid a brief is.

### 6.3 Calibration *(deferred post-v0.1)*
Brier score / ECE of claim confidences requires adjudicated ground truth, and
adjudicating scientific claims is expert labeling work with a nontrivial
protocol (many claims have no binary truth value). v0.1 ships confidence as
author-stated and unvalidated, documented as such; the adjudication workflow
and this metric family move to the post-v0.1 list together.

### 6.4 Foraging efficiency *(gated via proxy)*
The reading-order study (new-pins-per-read under frontier vs. relevance vs.
random ordering) uses a **scripted agent reader with a fixed pin budget** as
the reader — decided and costed in Phase 2, with traces collected during M5
dogfooding (the frontier scorer that generates orderings lands there), not in
review week. Because that study is research-grade work, the
v0.1 **gate** is a cheaper proxy: recall@budget of ground-truth included
studies under frontier ordering must beat relevance-only ordering on the
majority of §6.1 benchmarks. If it doesn't, frontier ships marked
*experimental* and the release notes say so. The full reading-order study is
report-only for v0.1.

### 6.5 Agent integration *(report-only)*
Scripted end-to-end tasks ("produce a brief on X with ≥15 supported claims")
run by an MCP-connected agent with and without foragekit tools: task success,
wall-clock, tokens, and audit findings on the result.

## 7. Distribution & OSS posture

- PyPI package `foragekit`, CLI entry point `forage`. Apache-2.0.
- **Zero-friction agent entry:** `uvx foragekit serve --mcp` / `pipx run
  foragekit` work with no prior install; the server is listed in MCP
  registries and directories at launch, and `agents/SKILL.md` ships in-repo
  as the copy-paste onboarding path for any agent framework.
- `CONTRIBUTING.md`, code of conduct, issue/PR templates, `SECURITY.md`,
  good-first-issue labels from day one. Connectors are the designed
  first-contribution surface — community connectors must pass the conformance
  suite (politeness, static hosts) and their hosts must be accepted into the
  curated scholarly-API registry to be listed.
- Semantic versioning; `0.x` may break APIs with changelog notice.

## 8. Non-goals (permanent)

foragekit is for literature review and knowledge work only. Because "we won't
build it" and "the design prevents it" are different strengths of claim, the
non-goals are labeled honestly:

**Enforced by design (for conforming components):**
1. **No covert or generic collection.** Connector hosts are validated against
   a curated scholarly-API registry at registration (unlisted hosts require an
   explicit per-workspace user override); full-text fetching is restricted to
   the curated OA registry with no generic-URL path; every request sends an
   honest User-Agent with a contact address; no headless browser, no
   credentialed scraping, no proxy rotation, no captcha solving. Honesty
   clause: locally installed Python code can always make its own network
   calls — the enforcement claim covers foragekit's own surfaces and any
   conforming plugin, and the project will not merge or list connectors that
   step outside it.
2. **No person-centric data model.** The connector contract exposes works and
   citations, not author-entity endpoints; the per-brief independence
   heuristic (§2.4) is never persisted and builds no author graph.

**Enforced by project policy (design cannot prevent free-text use):**
3. **No offensive security / OSINT features.** No recon tooling, no dossier
   workflows. Research questions are free text and a determined user can ask
   about anything — the design-level commitments are #1 and #2 above; the
   policy commitment is that no feature will be built to serve person-subject
   investigation.
4. **No biosafety workflows.** No lab-protocol planning or wet-lab
   integrations. It reads and organizes literature.
5. **No persuasion systems.** No audience modeling, targeting, or message
   optimization. Briefs are for the asker's understanding, not for moving
   third parties.

PRs that add capabilities in these categories are closed with a pointer to
this section.
