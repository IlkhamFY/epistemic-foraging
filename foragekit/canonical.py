"""Text canonicalization and quote-snapping.

Verification never compares raw bytes: extracted text is full of ligatures,
soft hyphens, and reflowed whitespace. Both cached text and quotes pass
through the same versioned canonicalization, and a pin "verifies" when its
canonical quote occurs in the canonical cached text.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

# Bump when canonicalization rules change; stored on every cache entry and pin
# so upgrades trigger re-verification instead of mass invalidation.
EXTRACTOR_VERSION = "canon-1"

_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "æ": "ae", "œ": "oe",
}
_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"',
           "–": "-", "—": "-", " ": " ", "­": ""}


def canonicalize(text: str) -> str:
    """Unicode NFC, ligature expansion, dehyphenation, whitespace folding."""
    text = unicodedata.normalize("NFC", text or "")
    for src, dst in {**_LIGATURES, **_QUOTES}.items():
        text = text.replace(src, dst)
    # Dehyphenate across line breaks: "halluci-\nnation" -> "hallucination"
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass
class Span:
    text: str          # exact canonical span, pin-ready
    start: int         # char offset into canonical cached text
    end: int
    score: float       # similarity to the query (1.0 = exact)


def find_span(cached: str, query: str, min_score: float = 0.72) -> Span | None:
    """Quote-snap: locate the closest exact span for approximate wording.

    Slides a window (sized to the query) over the canonical cached text and
    scores with difflib; returns the best window trimmed to word boundaries.
    """
    hay = canonicalize(cached)
    needle = canonicalize(query)
    if not hay or not needle:
        return None
    exact = hay.lower().find(needle.lower())
    if exact != -1:
        return Span(hay[exact:exact + len(needle)], exact, exact + len(needle), 1.0)

    n = len(needle)
    step = max(8, n // 4)
    best: tuple[float, int] | None = None
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(needle.lower())
    for start in range(0, max(1, len(hay) - n // 2), step):
        window = hay[start:start + n + step]
        matcher.set_seq1(window.lower())
        score = matcher.ratio()
        if best is None or score > best[0]:
            best = (score, start)
    if best is None or best[0] < min_score:
        return None
    score, start = best
    end = min(len(hay), start + n + step)
    # trim to word boundaries
    while start > 0 and hay[start - 1].isalnum():
        start -= 1
    while end < len(hay) and hay[end - 1].isalnum() and end - start < n * 2:
        end += 1
    return Span(hay[start:end].strip(), start, end, score)
