# How foragekit calculates its scores

Every number foragekit produces is a transparent, deterministic formula —
no learned weights, no model calls. This page is the exact algorithm; the
implementation is `foragekit/scoring.py` (≈130 lines, stdlib only).

## 1. The frontier score (what should I read next?)

For each **unread** source `s` given a question `q`:

```
score(s) = 0.45·relevance(s,q) + 0.25·novelty(s) + 0.30·centrality(s) − cost(s)
```

Weights are configurable; every ranking logs the weights used to the ledger,
so runs are reproducible.

### relevance — Okapi BM25 (k1 = 1.5, b = 0.75)

Tokens = lowercased alphanumerics, stopworded, length > 2. Over the corpus of
the workspace's sources (title + abstract), with N docs and df(t) = number of
docs containing term t:

```
IDF(t)        = ln( (N + 1) / (1 + df(t)) )
relevance(s)  = Σ over question terms t in s:
                IDF(t) · tf(t)·(k1+1) / ( tf(t) + k1·(1 − b + b·len(s)/avglen) )
```

Batch-normalized to [0, 1] by the corpus maximum.

### novelty — TF-IDF cosine distance from what you've already read

Each source gets a TF-IDF vector (`(1+ln tf)·IDF`). Sources you've marked
skimmed/read define a centroid; `novelty(s) = 1 − cosine(s, centroid)`.
No reads yet → 0.5 for everyone. This is what pushes the frontier *away*
from the cluster you've absorbed — reading the same neighborhood again
scores progressively worse.

### centrality — citation degree

`degree(s) / max_degree` within the workspace's snowball edge set. Sources
that many discovered papers cite (or that cite many) rank up: they're the
hubs of the patch you're in.

### cost

`0.15` when the source has no cached text (harder to verify pins against),
else `0`.

## 2. The patch-leaving signal (when should I stop?)

Foraging theory's marginal value theorem, discretized: over the last 4
sources marked read, count new pins + new claims. If the sum is 0, the
frontier reports `patch_exhausted: true` with advice to switch queries or
clusters. Advisory only — it never blocks.

## 3. Library mode (use the scorer in your own pipeline)

Both primitives are importable with no workspace and no network:

```python
from foragekit import score_passages, verify_quote

scores = score_passages(question, retrieved_texts)   # [0,1] per text, BM25 over the batch
span   = verify_quote(claim, chunk_text)             # exact supporting span, or None
```

`verify_quote` is the evidence gate: canonicalization (Unicode NFC, ligature
expansion, dehyphenation, whitespace folding — see `canonical.py`) followed
by exact containment (score 1.0) or windowed `difflib.SequenceMatcher`
fuzzy matching (accepted above 0.72). A returned `Span` carries the exact
text and character offsets — a machine-checkable receipt. `None` means
"this text does not support that claim": a binary reviewer verdict with no
context-window expansion and no GPU.

`examples/rag_reviewer.py` is a runnable writer/reviewer loop using exactly
these two calls.

## 4. Honest limitations

- BM25 and TF-IDF are lexical: paraphrases with zero term overlap score low.
  The SPEC reserves optional embeddings (`sqlite-vec`) as the upgrade path.
- `novelty` needs read-marks to mean anything; an agent that never marks
  sources read gets a static 0.5.
- The weights (0.45/0.25/0.30/0.15) are defaults that won one benchmark
  (docs/EVAL.md), not truths. Override per-call and measure with `evals/`.
