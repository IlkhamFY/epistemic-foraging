# foragekit

**Your agent can already search. foragekit makes it *forage*: hunt sources by expected information gain, pin every claim to a verified quote, and ship briefs that know how sure they are.**

> *Literature review is quietly becoming agent work — and agents are fast, tireless, and unaccountable. They cite from memory and present every claim with the same unearned confidence. The fix isn't a smarter model; it's giving the model the discipline we ask of a good PhD student: receipts, stances, and an honest "I'm not sure yet."* — the maintainers, July 2026

**News** · **2026-07** working core + MCP server land: 21 tools, zero runtime dependencies · **2026-07** head-to-head agent evaluation published ([docs/EVAL.md](docs/EVAL.md)) · **2026-07** spec and plan hardened by a four-critic adversarial review

![A foragekit brief: claims with verification tiers, a contested claim showing both sides, an audit-flagged unsupported claim, and a verified provenance ledger](https://raw.githubusercontent.com/IlkhamFY/epistemic-foraging/claude/ai-agent-discovery-tool-6uikck/docs/assets/hero.svg)

[Spec](docs/SPEC.md) · [Plan](docs/PLAN.md) · [Agent skill](agents/SKILL.md) · [Example brief](examples/brief-rag-hallucination.md) · [Eval results](docs/EVAL.md) · [What is epistemic foraging?](https://www.envisioning.com/vocab/epistemic-foraging)

## Get your agent foraging in 60 seconds

Zero runtime dependencies — Python stdlib only. Not on PyPI yet; from a clone:

```console
$ git clone https://github.com/IlkhamFY/epistemic-foraging && cd epistemic-foraging
$ claude mcp add forage -- python3 -m foragekit.cli serve     # Claude Code, one line
```

Or skip even that: the repo ships `.mcp.json` — open the clone in Claude Code or Cursor and the server is auto-detected. The workspace initializes itself on the first tool call. (Once the PyPI release lands: `uvx foragekit serve --mcp`.)

Then paste any of these at your agent:

- *"Register the question 'does creatine improve cognition?' and forage: search, snowball the best hits, read in frontier order, pin evidence, and compile a brief with confidence levels."*
- *"What should I read next, and is the current patch exhausted?"*
- *"Audit the workspace — which claims are single-source or contested?"*
- *"Replay the ledger: show me exactly what you did and verify the chain."*

For agents that follow written skills, drop in [`agents/SKILL.md`](agents/SKILL.md). For humans, the same loop is the `forage` CLI.

## Why foragekit?

- **Agents hallucinate citations.** foragekit makes "no pin, no claim" mechanical: a claim without a verbatim, canonical-match-verified quote is flagged `unsupported` by a machine audit, not by hoping someone notices.
- **Search is not foraging.** Relevance ranking reads what looks similar; the `frontier` ranks unread sources by expected information gain (relevance + novelty + citation centrality − reading cost, per-component explainable) and tells you when a patch is exhausted — foraging theory's marginal-value rule, applied to reading.
- **Confidence is usually decoration.** Here every claim carries author-stated confidence plus derived status — `supported` / `contested` / `unsupported` / `stale` — and contested claims render both sides instead of the convenient one.
- **Agent work is unauditable.** Every mutation lands in a hash-chained, append-only ledger attributed to the actor (`agent:claude`, `human:you`). `forage log --verify` proves nothing was rewritten after the fact.

## Quick tour (real output)

```console
$ forage ask "Do retrieval-augmented LLMs hallucinate less than closed-book LLMs?"
question q1 registered (uncertainty: high)

$ forage search "retrieval augmented generation hallucination" --limit 10
10 sources added (0 duplicates merged)

$ forage snowball src_99b22d --budget 20
20 sources added from citation graph

$ forage frontier --question q1 --top 3 --explain
 1. 0.575  src_ffe035  (2024) A Survey on RAG Meeting LLMs: Towards Retrieval-Augmented...
      highly relevant to the question
 2. 0.529  src_99b22d  (2024) Reducing hallucination in structured outputs via RAG
      central in the citation neighborhood
 3. 0.474  src_680255  (2026) A Review on Retrieval-Augmented Generation: Architectures...
      highly relevant to the question
patch signal: patch still yielding

$ forage pin src_1a03ce --find "RAG emerged as a promising solution" --loc "abstract ¶1"
evidence ev2 pinned (verified-abstract)
"Augmented Generation (RAG) has emerged as a promising solution by incorporating
 knowledge from external databases."

$ forage claim add "RAG mitigates LLM hallucination but does not eliminate it" \
    --evidence ev2:supports --confidence 0.7 --question q1
claim c1 added (status: supported)

$ forage audit
[single-source-claim] c1: RAG mitigates LLM hallucination but does not eliminate it
[unsupported-claim]  c2: RAG fully eliminates hallucination

$ forage log --verify | tail -1
chain: VERIFIED - ledger intact
```

And `forage brief q1` compiles the artifact — see a real one, generated end-to-end by an agent, in [`examples/brief-rag-hallucination.md`](examples/brief-rag-hallucination.md).

## The MCP surface

21 tools over stdio; every write is ledger-attributed to the calling agent. Grouped by loop stage:

| stage | tools |
|---|---|
| questions | `forage_ask` · `forage_list_questions` · `forage_update_question` |
| discovery | `forage_search` · `forage_snowball` · `forage_list_sources` · `forage_get_source` |
| reading | `forage_fetch_text` · `forage_get_source_text` (windowed) · `forage_find_text` (quote-snap) · `forage_mark_read` · `forage_frontier` · `forage_status` |
| evidence | `forage_pin_evidence` · `forage_add_claim` · `forage_link_evidence` · `forage_get_claim` · `forage_get_evidence` |
| synthesis | `forage_brief` · `forage_audit` · `forage_log` |

Nothing returns a whole paper in one call — text is windowed, lists paginate, briefs can write to disk and return a summary. And **the server teaches the agent**: the MCP handshake injects the foraging loop as server instructions, and every tool response ends with a one-line `next` hint — so a cold agent with zero prompting still forages instead of flailing. Full contracts in [SPEC §5.1](docs/SPEC.md#51-mcp-tools-the-agent-surface).

## The idea's lineage

"Epistemic foraging" isn't our coinage — it's [an established concept](https://www.envisioning.com/vocab/epistemic-foraging): *an agent's active search for information to reduce uncertainty about its environment*, rather than pursuing immediate reward. foragekit is a deliberately practical implementation of three research threads:

- **Active inference / epistemic value** (Karl Friston et al.) — behavior decomposes into pragmatic (reward-seeking) and epistemic (uncertainty-reducing) action; the frontier score is a working approximation of epistemic value for reading.
- **Information foraging theory** (Pirolli & Card) — humans hunt information the way animals hunt food, following "scent"; the frontier's `why` strings are scent made explicit.
- **Optimal foraging / the marginal value theorem** (Charnov) — leave a patch when its marginal yield drops below what's available elsewhere; that is literally the `patch_exhausted` signal.

## Design choices

- **Local-first, nothing else.** One workspace directory: SQLite + Markdown + JSONL. Delete it and nothing remains. No cloud, no telemetry, no account.
- **Zero runtime dependencies.** Stdlib only — the MCP server is 300 lines of hand-rolled JSON-RPC. `pip install` cannot fail on a transitive pin.
- **One explainable score, not a learned ranker.** Frontier weights are visible, configurable, and logged per ranking. You can argue with it, which is the point.
- **Connectors are an allowlist, not a framework.** OpenAlex and arXiv today (Crossref and Semantic Scholar specced); static hosts, polite rate limits, honest User-Agent, zero API keys. There is no generic-URL fetcher, by design.
- **MCP over stdio only.** No network listener until an authenticated HTTP design earns its way in ([SPEC §5.3](docs/SPEC.md#53-http-api--deferred-post-v01)).

**Status — honest edition:** this is a working walking skeleton. Evidence pins verify against cached *abstracts* (full-text PDF extraction is milestone M3); Crossref/Semantic Scholar connectors and confidence calibration are specced but unbuilt; PyPI release pending. The [plan](docs/PLAN.md) says what lands when.

## What it will never do

Literature review and knowledge work only. Enforced **by design**: no generic or covert collection (curated host allowlist, no crawler, no credentialed scraping) and no person-centric data model (works and citations only — no author-entity endpoints, no dossier primitives). Enforced **by policy**: no offensive-security/OSINT features, no biosafety workflows, no persuasion systems. Full text and the honest design-vs-policy split in [SPEC §8](docs/SPEC.md#8-non-goals-permanent).

<details>
<summary><b>Names we considered</b></summary>

Generated through three lenses (foraging metaphor, descriptive dev-tool, epistemics brand), web-checked for collisions: **foragekit** (chosen — says what it does, no exact collision), *trailcairn* (great provenance metaphor, misses discovery), *credence* (best epistemics word, crowded namespace), *tekmerion* (Aristotle's "sure sign", unspellable), *notesynth* (clear, generic).
</details>

## Wanted: connectors & adapters

The extension surface is deliberately small and these slots are open — each is a good first issue: **Crossref connector** · **Semantic Scholar connector** · **Zotero / CSL-JSON export adapter** · **brief output formats** · **README translations**. See [CONTRIBUTING.md](CONTRIBUTING.md) for the conformance rules (and the scope rules PRs are checked against).

## License

Apache-2.0 (see [`LICENSE`](LICENSE)).
