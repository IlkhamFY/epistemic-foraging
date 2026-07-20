# Does foragekit actually improve agent research? A first measurement

*July 2026 · n=1 per arm · run with Claude-class agents · read the
[limitations](#limitations) before quoting the numbers.*

## Setup

Two agents of the same model class researched the same question, once each:

> *Do retrieval-augmented LLMs hallucinate less than closed-book LLMs, and
> under what conditions does RAG fail to prevent hallucination?*

- **Arm A (baseline):** WebSearch + WebFetch only. Instructed to produce ≥6
  claims, each with confidence and at least one verbatim quote with source.
- **Arm B (foragekit):** the `forage` CLI only (no web tools), following the
  loop in [`agents/SKILL.md`](../agents/SKILL.md). Same claim requirements.

Afterwards, an **independent verifier agent** (same for both arms, blind to
which tool produced which brief) fetched every cited source and judged every
quoted passage: *verbatim* / *paraphrase* / *not found* / *unfetchable*.

## Results

| | baseline (websearch) | foragekit |
|---|---|---|
| sources discovered | 12 examined | **113 in workspace** (23 read, frontier-ordered) |
| claims produced | 8 | 8 |
| quotes / pins | 21 | 21 pins (26 footnote citations) |
| **independently verified verbatim** | **19/21 (90.5%)** | **26/26 (100%)** |
| paraphrases presented as quotes | 2 | 0 |
| fabricated quotes | 0 | 0 |
| contested claims captured structurally | 0 | 1 (both sides rendered, confidence 0.15) |
| unsupported claims shipped | n/a (nothing checks) | 0 (audit-enforced) |
| machine-checkable provenance | none | hash-chained ledger, `log --verify` passed |
| wall-clock | 5.0 min | 20.7 min (**4.1×**) |
| tokens | ~59k | ~84k (**1.4×**) |
| tool calls | 25 | 64 |

**Verification cost asymmetry (the point of the tool):** checking the
baseline's 21 quotes required a second agent making 15 tool calls over ~4.4
minutes and ~54k tokens — a full re-research pass. Checking foragekit's pins
is `forage audit && forage log --verify`: milliseconds, no model, no network.
The independent verifier run for arm B was belt-and-suspenders for this
report; day to day, the machine check *is* the check.

## Reading the numbers honestly

- **The baseline is good.** 90.5% verbatim with zero fabrications is a strong
  agent doing careful work. The failure mode is subtle: both misses were real
  content **paraphrased inside quotation marks** (a compressed sentence head;
  a changed verb inflection without brackets). A human reviewer cannot see
  those without re-fetching every source — which is precisely the trust
  problem: with the baseline you inherit 21 claims to *believe*; with
  foragekit you inherit 21 pins you can *check*.
- **Same claim count, different epistemics.** Both arms produced 8 claims.
  foragekit's carried stance structure (one claim demoted to *contested* with
  contradicting evidence attached at confidence 0.15) and per-claim
  independent-source counts up to 6; the baseline noted conflicts in prose,
  where no downstream tool can act on them.
- **Discovery scale vs. reading discipline.** foragekit's snowballing built a
  113-source candidate pool and the frontier chose 23 to read; the baseline
  examined the 12 sources its searches surfaced. Bigger pool ≠ better brief by
  itself — but it is what makes "what should I read next" a real question,
  and the eval's per-claim source diversity came from it.
- **The costs are real.** 4.1× wall-clock (polite rate limiting + 2.6× tool
  calls) and 1.4× tokens. For a quick answer, don't forage. For a brief
  someone will rely on, the overhead buys verifiability that the baseline
  cannot offer at any price after the fact.

## Frictions found (all real, two fixed)

Running the eval surfaced genuine issues, which was half the point:

1. `forage claim add --evidence` silently dropped repeated flags (argparse
   kept the last one) — **fixed** in the same commit as this report.
2. arXiv's API throttled hard (429s) under parallel agent load despite
   per-process politeness — the eval arm fell back to OpenAlex. Cross-process
   rate coordination is now a known M2 work item.
3. Some OpenAlex records carry citation lines instead of abstracts
   (`text_status` correctly reports it; the agent skipped them for pinning).
   Coverage in this run: ~90% of sources had usable abstracts.

## Limitations

n=1 per arm, one question, one domain (ML literature — friendly territory for
OpenAlex/arXiv). The tool's authors designed the eval. The verifier is an LLM
judge, though its task (string comparison against fetched text) is about as
LLM-judge-safe as tasks get. Evidence is abstract-tier only in the walking
skeleton — full-text pins (M3) should strengthen both the quotes and the
claims they can support. Treat this as *the first data point and the eval
harness working end-to-end*, not a benchmark result; the real gates are
specced in [SPEC §6](SPEC.md#6-evaluation-metrics).

## Follow-up: the cold-agent test (server-taught, zero prompting)

The original foragekit arm was *taught* — its prompt spelled out the loop in
~400 words. After shipping the self-teaching change (loop instructions in the
MCP handshake, a `next` hint on every tool/CLI response), we re-ran the
harder version: a fresh agent, a **new question** (spaced repetition vs.
massed practice), and a prompt that said only *"the machine has a research
tool called `forage`"* — no loop description, no SKILL.md, no examples.

Result: the cold agent ran the full designed loop unprompted —
`ask → search → frontier → snowball → fetch-text → text → pin → claim →
audit → brief` — produced 7 claims (5 supported, **2 contested with both
sides pinned**), 15 verified pins across 69 discovered sources, fixed an
audit finding before compiling, and left a 60-entry hash-verified ledger
fully attributed to `agent:cold-test`. Wall-clock 8.8 min, ~76k tokens.

The prompting cost of correct tool use dropped from ~400 words to zero. That
was the point of making the server teach the agent; one run says it works,
the same n=1 caveats apply.

## The M-E harness lands: first seed-reconstruction numbers

The reusable eval harness (`evals/`, PLAN milestone M-E) now implements SPEC
§6.1 and §6.4: hide a survey's bibliography, start from the question plus two
seed papers, measure recall of the hidden references at a fixed connector
budget. First benchmark — Huang et al.'s LLM-hallucination survey, 212
OpenAlex-resolvable references as ground truth, 25-request budget per arm:

| | keyword search only | foraging (search + iterative snowball) |
|---|---|---|
| requests used | 3 (queries exhausted) | 26 |
| sources discovered | 67 | 446 |
| **hidden references found** | **2/212 (0.9%)** | **53/212 (25.0%)** |

And the §6.4 ordering proxy — frontier vs. relevance-only ordering over the
*same* discovered pool (53 targets present):

| | recall@10 | recall@25 | first target at rank |
|---|---|---|---|
| frontier | **3.8%** | **11.3%** | **2** |
| relevance-only | 1.9% | 5.7% | 8 |

The frontier gate passes its first test: expected-information-gain ordering
roughly doubles relevance ordering at both cutoffs. Caveats as ever: one
benchmark, recency-picked seeds (favorable), a deliberately simple keyword
baseline, and a 100%-reachable ceiling by construction. The harness also
earned its keep on its first run by crashing: OpenAlex 400s on queries
containing `?` (wildcard syntax), which would have hit any agent passing a
research question verbatim — fixed at the connector layer the same day.

Reproduce: `python -m evals.run_eval evals/datasets/llm-hallucination-survey.json --budget 25`

## Artifacts

- The foragekit arm's unedited output: [`examples/brief-rag-hallucination.md`](../examples/brief-rag-hallucination.md)
- Reproduce: `pip install -e . && forage --help`, then follow
  [`agents/SKILL.md`](../agents/SKILL.md) with the question above.
