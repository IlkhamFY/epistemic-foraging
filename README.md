# foragekit

**An open-source toolkit that helps your agents do epistemic foraging: hunt for the right sources, pin the evidence, and write notes that know how sure they are.**

> Epistemic foraging is the behavior of an agent that actively seeks out information to
> reduce uncertainty in its model of the world, rather than simply pursuing immediate
> rewards. foragekit turns that idea into working infrastructure for literature review
> and knowledge work.

## Product thesis

Agents and researchers doing literature review all fail the same way: discovery is a pile of one-shot keyword searches, "evidence" is a citation pasted from memory, and the final write-up presents every claim with the same unearned confidence. foragekit is a local-first workspace — a CLI, a Python library, and an MCP server — that makes the full evidence loop first-class: it discovers sources through scholarly APIs and citation snowballing, ranks the reading frontier by *expected information gain* against your open questions instead of raw relevance, pins every claim to verbatim, hash-stamped quotes with resolvable locators, and compiles briefs where each claim carries its support status (supported / contested / single-source / stale) and a calibrated confidence. Because it ships as MCP tools, any agent can forage instead of guess — and because every mutation lands in an append-only provenance ledger, a human can audit exactly where every sentence came from. Scope is deliberately narrow: literature review and knowledge synthesis, nothing else.

## What it does

- **Source discovery** — query allowlisted scholarly APIs (OpenAlex, Crossref, arXiv, Semantic Scholar), then *snowball*: walk citations forward and backward from what you've already found, with deduplication across connectors.
- **Foraging, not just searching** — you register *open questions*; the `frontier` command ranks unread sources by expected information gain (relevance × novelty × citation centrality − reading cost) and tells you when a "patch" (a query or citation neighborhood) is exhausted and it's time to move on.
- **Evidence tracking** — evidence is a verbatim quote + locator + retrieval timestamp + content hash, pinned to a cached copy of the source. Claims link to evidence with an explicit stance (supports / contradicts / mentions). No pin, no claim.
- **Uncertainty-aware synthesis** — `brief` compiles your claims into a Markdown report where every claim is annotated with confidence, source count, source independence, and contestation. `audit` flags unsupported claims, single-source claims, contradicted claims, and stale or unresolvable evidence.
- **Agent-native** — every capability is exposed as an MCP tool, so Claude, or any MCP-capable agent, can run the whole loop: ask → search → snowball → pin → claim → brief → audit.
- **Local-first and auditable** — one workspace directory: SQLite store, Markdown notes you own, cached source text, and an append-only JSONL ledger recording every mutation (by whom — human or agent — and when).

## What it will never do

foragekit is for literature review and knowledge work, and the boundaries are enforced in the design, not just stated in the README:

- **No offensive-security tooling.** Not a recon or OSINT framework. Sources are documents, not people; there is no person-centric entity resolution and no dossier building.
- **No biosafety workflows.** No lab-protocol planners, no wet-lab integrations. It reads and organizes literature; domain-specific hazard workflows are out of scope.
- **No persuasion systems.** No audience targeting, message optimization, or A/B rhetoric features. Output is calibrated briefs for the person who asked, not content tuned to move someone else.
- **No covert data collection.** Connectors are an allowlist of public scholarly APIs; there is no generic crawler, no headless browser, no login-walled scraping, no proxy rotation, and no plugin hook that could add them. Every request sends an honest User-Agent with a contact address and respects rate limits and terms of service.

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

$ forage pin src_4f2a --quote "hallucination rates dropped from 38% to 12%" --loc "§5.2, p.7"
evidence ev_9c31 pinned (sha256:ab12…)

$ forage claim add "RAG reduces but does not eliminate hallucination" \
    --evidence ev_9c31,ev_77d0 --confidence 0.8 --question q1

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
