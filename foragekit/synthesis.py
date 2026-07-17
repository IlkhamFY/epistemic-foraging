"""Brief compilation, audit, and export."""
from __future__ import annotations

import time

STANCES = ("supports", "contradicts", "mentions")


def derive_status(links: list[dict], evidence_by_id: dict,
                  stale_days: float = 365.0) -> str:
    """Total derivation per SPEC §1: contested > supported > unsupported,
    with a stale overlay. `mentions` links never count."""
    supporting = [l for l in links if l["stance"] == "supports"]
    contradicting = [l for l in links if l["stance"] == "contradicts"]
    if contradicting:
        return "contested"
    if not supporting:
        return "unsupported"
    cutoff = time.time() - stale_days * 86400
    pins = [evidence_by_id[l["evidence_id"]] for l in supporting + contradicting
            if l["evidence_id"] in evidence_by_id]
    if pins and all((p.get("retrieved_at") or 0) < cutoff for p in pins):
        return "stale"
    return "supported"


def independent_source_count(links: list[dict], evidence_by_id: dict,
                             sources_by_id: dict) -> int:
    """Per-brief heuristic, never persisted (SPEC §2.4): sources sharing any
    author string count once. No author entities are built or stored."""
    groups: list[set[str]] = []
    for l in links:
        ev = evidence_by_id.get(l["evidence_id"])
        if not ev:
            continue
        src = sources_by_id.get(ev["source_id"])
        if not src:
            continue
        authors = {a.strip().lower() for a in (src.get("authors") or [])}
        for g in groups:
            if g & authors:
                g |= authors
                break
        else:
            groups.append(authors or {f"__solo_{ev['source_id']}"})
    return len(groups)


def _cite(src: dict) -> str:
    authors = src.get("authors") or []
    first = authors[0].split()[-1] if authors else "Unknown"
    tail = " et al." if len(authors) > 1 else ""
    year = src.get("year") or "n.d."
    return f"{first}{tail} ({year}), *{src.get('title', '?')}*"


def compile_brief(question: dict, claims: list[dict], links_by_claim: dict,
                  evidence_by_id: dict, sources_by_id: dict,
                  badge: bool = True) -> str:
    order = ["supported", "contested", "unsupported", "stale"]
    by_status: dict[str, list[dict]] = {s: [] for s in order}
    for c in claims:
        status = derive_status(links_by_claim.get(c["id"], []), evidence_by_id)
        by_status[status].append(c)

    lines = [f"# Brief: {question['text']}", "",
             f"question `{question['id']}` · status: {question['status']} · "
             f"uncertainty: {question['uncertainty']}", ""]
    fn = 0
    footnotes: list[str] = []
    total_pins = 0
    for status in order:
        group = by_status[status]
        if not group:
            continue
        marker = {"supported": "✅", "contested": "⚖️",
                  "unsupported": "⚠️ ", "stale": "🕰"}[status]
        lines.append(f"## {marker} {status.capitalize()} ({len(group)})")
        lines.append("")
        for c in group:
            links = links_by_claim.get(c["id"], [])
            refs = []
            for l in links:
                ev = evidence_by_id.get(l["evidence_id"])
                if not ev:
                    continue
                fn += 1
                total_pins += 1
                src = sources_by_id.get(ev["source_id"], {})
                refs.append(f"[^{fn}]")
                footnotes.append(
                    f"[^{fn}]: ({l['stance']}, {ev.get('verification', '?')}) "
                    f"\"{ev['quote']}\" — {_cite(src)}, {ev.get('locator') or 'no locator'}")
            ind = independent_source_count(links, evidence_by_id, sources_by_id)
            conf = c.get("confidence")
            conf_s = f", confidence {conf:.2f} (author-stated)" if conf is not None else ""
            lines.append(f"- **{c['text']}** ({c['id']}{conf_s}, "
                         f"{ind} independent source{'s' if ind != 1 else ''})"
                         + "".join(refs))
        lines.append("")
    if footnotes:
        lines.append("## Evidence")
        lines.append("")
        lines.extend(footnotes)
        lines.append("")
    if badge:
        lines.append("---")
        lines.append(f"*foraged with [foragekit](https://github.com/IlkhamFY/epistemic-foraging) · "
                     f"{len(claims)} claims, {total_pins} pinned quotes, provenance ledger included*")
    return "\n".join(lines)


def audit(claims: list[dict], links_by_claim: dict, evidence_by_id: dict,
          sources_by_id: dict) -> dict:
    findings: list[dict] = []
    linked_ev = {l["evidence_id"] for links in links_by_claim.values() for l in links}
    for c in claims:
        links = links_by_claim.get(c["id"], [])
        status = derive_status(links, evidence_by_id)
        if status == "unsupported":
            findings.append({"kind": "unsupported-claim", "claim": c["id"],
                             "detail": c["text"][:90]})
        if status == "contested":
            findings.append({"kind": "contested-claim", "claim": c["id"],
                             "detail": "has contradicting evidence - brief renders both sides"})
        supporting_sources = {evidence_by_id[l["evidence_id"]]["source_id"]
                              for l in links if l["stance"] == "supports"
                              and l["evidence_id"] in evidence_by_id}
        if len(supporting_sources) == 1:
            findings.append({"kind": "single-source-claim", "claim": c["id"],
                             "detail": c["text"][:90]})
    for ev_id, ev in evidence_by_id.items():
        if ev_id not in linked_ev:
            findings.append({"kind": "orphaned-pin", "evidence": ev_id,
                             "detail": ev["quote"][:90]})
        if ev.get("verification") == "unverified-locator":
            findings.append({"kind": "unverified-pin", "evidence": ev_id,
                             "detail": "no cached text to verify against"})
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    return {"ok": not findings, "counts": counts, "findings": findings}


def export_bibtex(sources: list[dict]) -> str:
    out = []
    for s in sources:
        key = (s.get("authors") or ["anon"])[0].split()[-1].lower() + str(s.get("year") or "")
        fields = {
            "title": s.get("title"), "year": s.get("year"),
            "author": " and ".join(s.get("authors") or []),
            "journal": s.get("venue"), "doi": s.get("doi"),
            "eprint": s.get("arxiv_id"),
        }
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        out.append(f"@article{{{key},\n{body}\n}}")
    return "\n\n".join(out)
