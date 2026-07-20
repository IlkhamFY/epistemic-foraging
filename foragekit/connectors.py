"""Scholarly-API connectors: OpenAlex, arXiv, and Crossref.

Design rules from SPEC §2.1 apply even at this stage: static host allowlist,
honest User-Agent, polite rate limiting, works-and-citations surface only.
There is no generic-URL fetch path anywhere in this module: full text is
fetched only from the allowlisted arXiv HTML render (SPEC §2.1 OA registry).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser

USER_AGENT = "foragekit/0.0.2 (+https://github.com/IlkhamFY/epistemic-foraging)"
# Generic project contact for polite pools (Crossref mailto convention).
CONTACT = "foragekit@users.noreply.github.com"
ALLOWED_HOSTS = {"api.openalex.org", "export.arxiv.org", "arxiv.org",
                 "api.crossref.org"}
_MIN_INTERVAL = 0.35  # seconds between requests, per process
_last_request = 0.0


def _get(url: str) -> bytes:
    global _last_request
    host = urllib.parse.urlparse(url).netloc
    if host not in ALLOWED_HOSTS:
        raise PermissionError(f"host {host!r} is not in the connector allowlist")
    wait = _MIN_INTERVAL - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                _last_request = time.time()
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                _last_request = time.time()
                raise  # definitive client error (e.g. 404): retrying won't help
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


@dataclass
class SourceRecord:
    title: str
    connector: str
    openalex_id: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    urls: list[str] = field(default_factory=list)
    abstract: str | None = None
    referenced: list[str] = field(default_factory=list)  # openalex ids

    def dedupe_key(self) -> str:
        if self.doi:
            return "doi:" + self.doi.lower().removeprefix("https://doi.org/")
        if self.arxiv_id:
            return "arxiv:" + self.arxiv_id.lower()
        norm = "".join(c for c in (self.title or "").lower() if c.isalnum())
        return f"title:{norm[:80]}:{self.year or ''}"


# --- OpenAlex ---------------------------------------------------------------

def _oa_abstract(inv: dict | None) -> str | None:
    if not inv:
        return None
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos)) or None


def _oa_record(w: dict) -> SourceRecord:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    ids = w.get("ids") or {}
    arxiv = None
    for u in [loc.get("landing_page_url") or "", loc.get("pdf_url") or ""]:
        if "arxiv.org" in u:
            arxiv = u.rstrip("/").split("/")[-1].removesuffix(".pdf")
    return SourceRecord(
        title=w.get("display_name") or "(untitled)",
        connector="openalex",
        openalex_id=(w.get("id") or "").removeprefix("https://openalex.org/") or None,
        doi=(ids.get("doi") or "").removeprefix("https://doi.org/") or None,
        arxiv_id=arxiv,
        authors=[a.get("author", {}).get("display_name", "?") for a in w.get("authorships", [])][:12],
        year=w.get("publication_year"),
        venue=src.get("display_name"),
        urls=[u for u in [ids.get("doi"), loc.get("landing_page_url")] if u],
        abstract=_oa_abstract(w.get("abstract_inverted_index")),
        referenced=[r.removeprefix("https://openalex.org/") for r in w.get("referenced_works", [])],
    )


_OA_FIELDS = ("id,display_name,ids,publication_year,authorships,primary_location,"
              "abstract_inverted_index,referenced_works")


class OpenAlex:
    name = "openalex"

    def search(self, query: str, limit: int = 25) -> list[SourceRecord]:
        url = ("https://api.openalex.org/works?search=" + urllib.parse.quote(query)
               + f"&per-page={min(limit, 50)}&select={_OA_FIELDS}")
        data = json.loads(_get(url))
        return [_oa_record(w) for w in data.get("results", [])]

    def lookup_many(self, openalex_ids: list[str]) -> list[SourceRecord]:
        out: list[SourceRecord] = []
        for i in range(0, len(openalex_ids), 40):
            batch = "|".join(openalex_ids[i:i + 40])
            url = (f"https://api.openalex.org/works?filter=openalex_id:{batch}"
                   f"&per-page=50&select={_OA_FIELDS}")
            data = json.loads(_get(url))
            out.extend(_oa_record(w) for w in data.get("results", []))
        return out

    def cited_by(self, openalex_id: str, limit: int = 25) -> list[SourceRecord]:
        url = (f"https://api.openalex.org/works?filter=cites:{openalex_id}"
               f"&per-page={min(limit, 50)}&sort=cited_by_count:desc&select={_OA_FIELDS}")
        data = json.loads(_get(url))
        return [_oa_record(w) for w in data.get("results", [])]


# --- arXiv -------------------------------------------------------------------

_ATOM = "{http://www.w3.org/2005/Atom}"

# Elements whose entire subtree is markup noise for plain-text purposes:
# scripts/styles, page chrome, and MathML (its <annotation> carries raw LaTeX).
_HTML_SKIP_TAGS = {"script", "style", "nav", "head", "header", "footer",
                   "math", "svg", "button", "select", "template", "aside"}
# Block-level boundaries become paragraph breaks so words never run together.
_HTML_BLOCK_TAGS = {"p", "div", "section", "article", "blockquote", "li", "ul",
                    "ol", "table", "tr", "td", "th", "figcaption", "figure",
                    "br", "h1", "h2", "h3", "h4", "h5", "h6"}


class _HTMLTextExtractor(HTMLParser):
    """Strip an HTML document down to paragraph text (stdlib html.parser)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _HTML_SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        # collapse runs of blank lines but keep paragraph breaks
        return re.sub(r"\n{2,}", "\n\n", raw).strip()


def html_to_text(html_doc: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html_doc)
    parser.close()
    return parser.text()


def fetch_arxiv_html(arxiv_id: str) -> str | None:
    """Fetch the arXiv HTML render and return plain paragraph text.

    Returns None when arXiv has no HTML render for this paper (HTTP 404 —
    common for pre-2024 submissions). Allowlist-only: the URL is built from
    the arXiv id, never taken from source urls[].
    """
    url = "https://arxiv.org/html/" + urllib.parse.quote(arxiv_id, safe="./")
    try:
        raw = _get(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return html_to_text(raw.decode("utf-8", "replace")) or None


class Arxiv:
    name = "arxiv"

    def search(self, query: str, limit: int = 25) -> list[SourceRecord]:
        url = ("https://export.arxiv.org/api/query?search_query="
               + urllib.parse.quote(f'all:"{query}"')
               + f"&max_results={min(limit, 50)}")
        root = ET.fromstring(_get(url))
        out = []
        for e in root.findall(_ATOM + "entry"):
            aid = (e.findtext(_ATOM + "id") or "").rstrip("/").split("/abs/")[-1]
            published = e.findtext(_ATOM + "published") or ""
            out.append(SourceRecord(
                title=" ".join((e.findtext(_ATOM + "title") or "").split()),
                connector="arxiv",
                arxiv_id=aid or None,
                authors=[a.findtext(_ATOM + "name") or "?" for a in e.findall(_ATOM + "author")][:12],
                year=int(published[:4]) if published[:4].isdigit() else None,
                venue="arXiv",
                urls=[f"https://arxiv.org/abs/{aid}"] if aid else [],
                abstract=" ".join((e.findtext(_ATOM + "summary") or "").split()) or None,
            ))
        return out


# --- Crossref ----------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_jats(xml_text: str | None) -> str | None:
    """Crossref abstracts are JATS XML; reduce to plain text."""
    if not xml_text:
        return None
    text = unescape(_TAG_RE.sub(" ", xml_text))
    text = re.sub(r"\s+", " ", text).strip()
    # drop a leading "Abstract" heading left over from <jats:title>
    text = re.sub(r"^abstract\s+", "", text, flags=re.IGNORECASE)
    return text or None


def _cr_year(item: dict) -> int | None:
    for key in ("published", "published-print", "published-online", "issued"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return parts[0][0]
    return None


def _cr_record(item: dict) -> SourceRecord:
    doi = item.get("DOI") or None
    titles = item.get("title") or []
    containers = item.get("container-title") or []
    authors = []
    for a in item.get("author", [])[:12]:
        name = " ".join(p for p in [a.get("given"), a.get("family")] if p).strip()
        authors.append(name or a.get("name") or "?")
    doi = doi.lower() if doi else None
    urls: list[str] = []
    for u in [f"https://doi.org/{doi}" if doi else None, item.get("URL")]:
        if u and u.lower() not in [x.lower() for x in urls]:
            urls.append(u)
    return SourceRecord(
        title=" ".join((titles[0] if titles else "").split()) or "(untitled)",
        connector="crossref",
        doi=doi,
        authors=authors,
        year=_cr_year(item),
        venue=(containers[0] if containers else None) or None,
        urls=urls,
        abstract=_strip_jats(item.get("abstract")),
    )


class Crossref:
    name = "crossref"

    def search(self, query: str, limit: int = 25) -> list[SourceRecord]:
        params = urllib.parse.urlencode({
            "query": query, "rows": min(limit, 50), "mailto": CONTACT})
        url = "https://api.crossref.org/works?" + params
        data = json.loads(_get(url))
        items = (data.get("message") or {}).get("items") or []
        return [_cr_record(it) for it in items]


CONNECTORS = {"openalex": OpenAlex(), "arxiv": Arxiv(), "crossref": Crossref()}
