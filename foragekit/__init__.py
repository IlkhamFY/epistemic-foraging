"""foragekit: epistemic foraging for AI agents and researchers.

Two ways in:

- **Workspace mode** (the full loop): `Workspace` owns questions, sources,
  evidence pins, claims, and the hash-chained ledger. The CLI and MCP server
  are thin shells over it.
- **Library mode** (no workspace, no network): `score_passages` and
  `verify_quote` are deterministic primitives for embedding foragekit's
  evidence discipline inside an external RAG pipeline - e.g. a
  writer/reviewer loop where the reviewer gates each retrieved chunk without
  expanding any model's context window. See examples/rag_reviewer.py.
"""
from .canonical import Span, find_span
from .scoring import score_passages
from .workspace import Workspace

__version__ = "0.0.3"


def verify_quote(quote: str, text: str, min_score: float = 0.72) -> Span | None:
    """Reviewer-style evidence gate, no model call required.

    Returns the exact canonical span in `text` supporting `quote` (score 1.0
    for verbatim-after-canonicalization containment, lower for fuzzy matches
    above `min_score`), or None when the text does not support the quote.
    Treat `None` as the reviewer's "fail" verdict and a Span as "pass, with
    the receipt attached" - the Span's start/end are character offsets into
    the canonicalized text, usable as a locator.
    """
    return find_span(text, quote, min_score)


__all__ = ["Workspace", "Span", "find_span", "score_passages",
           "verify_quote", "__version__"]
