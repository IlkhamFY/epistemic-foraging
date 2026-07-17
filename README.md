# foragekit

**An open-source toolkit that helps your agents do epistemic foraging: hunt for the right sources, pin the evidence, and write notes that know how sure they are.**

> Epistemic foraging is the behavior of an agent that actively seeks out information to
> reduce uncertainty in its model of the world, rather than simply pursuing immediate
> rewards. foragekit turns that idea into working infrastructure for literature review
> and knowledge work.

## Product thesis

Agents and researchers doing literature review all fail the same way: discovery is a pile of one-shot keyword searches, "evidence" is a citation pasted from memory, and the final write-up presents every claim with the same unearned confidence. foragekit is a local-first workspace — a CLI, a Python library, and an MCP server — that makes the full evidence loop first-class: it discovers sources through scholarly APIs and citation snowballing, ranks the reading frontier by *expected information gain* against your open questions instead of raw relevance, pins every claim to verbatim quotes with verified locators — labeled honestly by verification tier, down to abstract-only when full text can't be cached — and compiles briefs where each claim carries its derived support status (supported / contested / unsupported / stale) and an explicit author-stated confidence. Because it ships as MCP tools, any agent can forage instead of guess — and because every mutation lands in a hash-chained, append-only provenance ledger, a human can audit where every sentence came from. Scope is deliberately narrow: literature review and knowledge synthesis, nothing else.

## What it does

- **Source discovery** — query allowlisted scholarly APIs (OpenAlex, Crossref, arXiv, Semantic Scholar), then *snowball*: walk citations forward and backward from what you've already found, with deduplication across connectors.
- **Foraging, not just searching** — you register *open questions*; the `frontier` command ranks unread sources by a weighted, explainable combination of relevance, novelty, and citation centrality, minus reading cost — and tells you when a "patch" (a query or citation neighborhood) is exhausted and it's time to move on.
- **Evidence tracking** — evidence is a verbatim quote + locator + retrieval timestamp + content hash, verified against a locally cached copy of the source. Every pin carries an honest verification tier: verified-full-text, verified-abstract, or unverified-locator when no text could be cached (common for paywalled sources — briefs say so instead of hiding it). Claims link to evidence with an explicit stance (supports / contradicts / mentions). No pin, no claim.
- **Uncertainty-aware synthesis** — `brief` compiles your claims into a Markdown report where every claim is annotated with confidence, source count, source independence, and contestation. `audit` flags unsupported claims, single-source claims, contested pairs, stale or degraded evidence, and orphaned pins.
- **Agent-native** — the full loop is exposed as MCP tools, so Claude, or any MCP-capable agent, can run it end to end: ask → search → snowball → fetch → read → pin → claim → brief → audit, including resuming an existing workspace in a fresh session.
- **Local-first and auditable** — one workspace directory: SQLite store, Markdown notes you own, cached source text, and a hash-chained, append-only JSONL ledger recording every mutation (by whom — human or agent — and when), verifiable with `forage log --verify`.

## Get your agent foraging in 60 seconds

The MCP server is the front door, and adoption friction is a design requirement, not an afterthought — no config file, no account, no setup script:

```console
$ claude mcp add forage -- uvx foragekit serve --mcp     # Claude Code, one line
$ uvx foragekit serve --mcp                              # any other MCP client
```

The workspace auto-initializes on the first tool call, so "install" and "first useful result" happen in the same minute. The repo ships a drop-in skill file — [`agents/SKILL.md`](agents/SKILL.md) — that teaches any agent to run the loop well; paste it into your agent's instructions or install it as a Claude Code skill.

And the output closes the loop: every compiled brief is a self-contained Markdown artifact — provenance footnotes inline, verification tiers visible, readable with no workspace — with a one-line footer (`foraged with foragekit · 17 claims, every one pinned`, removable via `--no-badge`). A brief you share is a brief that shows its receipts, and the receipts are the pitch.

## What it will never do

foragekit is for literature review and knowledge work only. Because "we won't build it" and "the design prevents it" are different strengths of claim, the boundaries are labeled honestly (full detail in [SPEC §8](docs/SPEC.md#8-non-goals-permanent)):

**Enforced by design:**
- **No covert or generic data collection.** Connector hosts are validated against a curated scholarly-API registry; full-text fetching is restricted to a curated open-access registry — there is no generic-URL fetcher, no headless browser, no credentialed scraping, no proxy rotation. Every request sends an honest User-Agent with a contact address and respects rate limits and terms of service. (Locally installed code can always make its own network calls — the claim covers foragekit's surfaces and conforming plugins, and out-of-scope connectors won't be merged or listed.)
- **No person-centric data model.** Sources are documents, not people: the connector contract exposes works and citations only — no author-entity endpoints, no persistent author graph, no dossier-building primitives.

**Enforced by project policy:**
- **No offensive-security or OSINT features.** Not a recon framework; no feature will be built to serve person-subject investigation.
- **No biosafety workflows.** No lab-protocol planners, no wet-lab integrations. It reads and organizes literature; domain-specific hazard workflows are out of scope.
- **No persuasion systems.** No audience targeting, message optimization, or A/B rhetoric features. Briefs are for the person who asked, not content tuned to move someone else.

## Quick tour

```console
$ forage init --workspace ./review
$ forage ask "Do retrieval-augmented LLMs hallucinate less than closed-book LLMs?"
question q1 registered (uncertainty: high)

$ forage search "retrieval augmented generation hallucination" --connector openalex --limit 25
25 sources added (7 duplicates merged)

$ forage snowball src_4f2a --direction both --depth 1
41 sources added from citation graph

$ forage frontier --question q1 --top 5
#  score  source                                                    why
1  0.87   Shuster et al. 2021 — Retrieval Augmentation Reduces...   high centrality, unread cluster
2  0.81   ...

$ forage fetch-text src_4f2a
full text cached from arxiv.org (extractor v1)

$ forage pin src_4f2a --find "hallucination rates dropped from 38 to 12" --loc "§5.2"
snapped to exact span at §5.2 ¶3 · evidence ev_9c31 pinned (verified-full-text, sha256:ab12…)

$ forage claim add "RAG reduces but does not eliminate hallucination" \
    --evidence ev_9c31:supports,ev_77d0:supports --confidence 0.8 --question q1

$ forage audit
✔ 14 claims supported   ⚠ 2 single-source   ✖ 1 contested (claims c7 ↔ c11)

$ forage brief q1 --format md > brief.md
$ forage serve --mcp        # expose the whole loop to your agent
```

## Documentation

- [`docs/SPEC.md`](docs/SPEC.md) — MVP specification: features, data model, architecture, CLI/API/MCP surface, evaluation metrics.
- [`docs/PLAN.md`](docs/PLAN.md) — implementation plan: plan → spec → implement → review, with milestones sized for a 2–3 person team.

## Names we considered

Candidates were generated through three lenses (foraging metaphor, descriptive dev-tool, epistemics brand) and web-checked for collisions with existing projects.

| name | angle | verdict |
|---|---|---|
| **foragekit** | the behavior + "-kit" says dev tool; `forage` is the CLI verb | ✅ **chosen** — says exactly what it does, ties the brand to epistemic foraging, no exact collision found (nearest: `forgekit`, a small unrelated PyPI package) |
| trailcairn | cairns: durable public trail markers others can retrace | strong provenance metaphor, collision-free — but says "evidence trail" and misses discovery/synthesis |
| credence | Bayesian degree of belief — notes that know how sure they are | best epistemics word, but a crowded namespace (Credence ID, CredenceAI, others) |
| tekmerion | Aristotle's "sure sign": evidence strong enough to ground a conclusion | collision-free and erudite — too erudite; nobody can spell it after hearing it once |
| notesynth | leads with the deliverable: synthesized notes | collision-free but generic, and undersells discovery + evidence tracking |

## Status

Concept stage. This repo currently contains the product thesis, MVP spec, and implementation plan. If the design resonates, open an issue — the spec is the thing to argue with right now.

## License

Apache-2.0 (see [`LICENSE`](LICENSE)).
