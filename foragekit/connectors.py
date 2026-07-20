"""Scholarly-API connectors: OpenAlex and arXiv (walking skeleton).

Design rules from SPEC §2.1 apply even at this stage: static host allowlist,
honest User-Agent, polite rate limiting, works-and-citations surface only.
There is no generic-URL fetch path anywhere in this module.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

USER_AGENT = "foragekit/0.0.2 (+https://github.com/IlkhamFY/epistemic-foraging)"
ALLOWED_HOSTS = {"api.openalex.org", "export.arxiv.org"}
_MIN_INTERVAL = 0.35  # seconds between requests, per process
_last_request = 0.0

# Request accounting: the eval harness compares strategies at equal budgets.
REQUEST_COUNT = {"n": 0}


def reset_request_count() -> None:
    REQUEST_COUNT["n"] = 0


def request_count() -> int:
    return REQUEST_COUNT["n"]


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
                REQUEST_COUNT["n"] += 1
                return resp.read()
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


class Arxiv:
    name = "arxiv"

    def search(self, query: str, limit: int = 25) -> list[SourceRecord]:
        url = ("https://export.arxiv.org/api/query?search_query="
               + urllib.parse.quote(f'all:"{query}"')
               + f"&max_results={min(limit, 50)}")
        return self._parse_feed(_get(url))

    def lookup(self, arxiv_id: str) -> SourceRecord | None:
        url = ("https://export.arxiv.org/api/query?id_list="
               + urllib.parse.quote(arxiv_id) + "&max_results=1")
        recs = self._parse_feed(_get(url))
        return recs[0] if recs else None

    def _parse_feed(self, raw: bytes) -> list[SourceRecord]:
        root = ET.fromstring(raw)
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


CONNECTORS = {"openalex": OpenAlex(), "arxiv": Arxiv()}
