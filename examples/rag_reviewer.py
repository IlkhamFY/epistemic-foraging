"""foragekit as a library inside your own RAG writer/reviewer loop.

The pattern a reviewer colleague asked for:

    while not done:
        sources = writer.run()          # your RAG retrieval (chromadb, .npz, ...)
        reviewer.run(sources)           # scores = [foragekit(source) for source in sources]

foragekit's role here is the reviewer's evidence gate - two deterministic,
model-free primitives, so you never expand the RAG context window (no i-1/i+1
neighbor fetching) and never spend GPU on verification:

    score_passages(question, texts)  -> batch relevance in [0, 1] (BM25)
    verify_quote(quote, text)        -> exact supporting span, or None

Honest scope note: verify_quote checks that a *cited quote* really occurs in
the text (canonicalized, typo-tolerant). It catches the classic failure of
RAG writers - paraphrases presented inside quotation marks - but it is not a
semantic entailment judge; a claim with zero lexical overlap needs your
reviewer model for that (docs/SCORING.md §4).

Run me directly: `python examples/rag_reviewer.py` (offline, no deps).
"""
from foragekit import score_passages, verify_quote

QUESTION = "Does retrieval augmentation reduce hallucination in language models?"

# Stand-in for writer.run(): retrieved chunks + what the writer *claims* each
# chunk says, as a quotation. The middle one is the classic hallucination:
# a paraphrase dressed up as a quote.
writer_output = [
    {"chunk": "Retrieval augmentation substantially reduces the well-known "
              "problem of knowledge hallucination in state-of-the-art chatbots.",
     "cited_quote": "substantially reduces the well-known problem of knowledge hallucination"},
    {"chunk": "We find that retrieval-augmented models still hallucinate when "
              "retrieved documents conflict with parametric knowledge.",
     "cited_quote": "retrieval reliably eliminates hallucination in all settings"},
    {"chunk": "The grassland biome supports a wide diversity of grazing "
              "mammals and seasonal grasses.",
     "cited_quote": "grassland biome supports a wide diversity"},
]


def reviewer_run(question: str, items: list[dict],
                 relevance_floor: float = 0.3) -> list[dict]:
    """Binary pass/fail per chunk, with receipts - no LLM in the loop.

    A chunk passes only when it is (a) relevant to the question and (b) the
    writer's cited quote genuinely occurs in it.
    """
    scores = score_passages(question, [it["chunk"] for it in items])
    verdicts = []
    for item, score in zip(items, scores):
        span = verify_quote(item["cited_quote"], item["chunk"])
        ok = score >= relevance_floor and span is not None
        reason = ("irrelevant to question" if score < relevance_floor
                  else "cited quote not found in chunk" if span is None else None)
        verdicts.append({
            "relevance": round(score, 3),
            "evidence": "pass" if ok else "fail",
            "reason": reason,
            "receipt": (f'"{span.text}" (chars {span.start}-{span.end}, '
                        f"match {span.score:.2f})") if ok and span else None,
            "chunk": item["chunk"][:55] + "...",
        })
    return verdicts


if __name__ == "__main__":
    for v in reviewer_run(QUESTION, writer_output):
        print(f"[{v['evidence']:4}] relevance={v['relevance']:.3f}  {v['chunk']}")
        print(f"       {'receipt: ' + v['receipt'] if v['receipt'] else 'why: ' + v['reason']}")
    print("\nOnly chunks that pass become evidence; fabricated quotes and\n"
          "off-topic chunks are dropped before reaching any model's context.")
