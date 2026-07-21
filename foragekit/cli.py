"""The forage CLI: a thin shell over foragekit.workspace.Workspace.

Every command maps 1:1 to a Workspace method — this module only parses
arguments, formats results (human lines plus `next:` hints, or pure --json),
and translates outcomes into stable exit codes (0 ok, 2 error / text not
found, 3 audit findings, 4 broken ledger). The MCP server in mcp_server.py
is the same shell for agents.
"""
from __future__ import annotations

import argparse
import json
import sys

from .hints import CLI_HINTS, audit_hint, frontier_hint
from .workspace import Workspace


def _out(args, data, human: str | None = None):
    """Print `human` in human mode, or the raw payload as JSON with --json."""
    if getattr(args, "json", False) or human is None:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(human)


def _hint(args, hint: str | None) -> int:
    """Print a next-step hint (human mode only, --json stays pure); exit 0."""
    if hint and not getattr(args, "json", False):
        print("\n" + hint)
    return 0


def _cmd_init(args, ws: Workspace) -> int:
    """Initialize a workspace (the Workspace constructor created the store)."""
    _out(args, {"workspace": str(ws.store.root)},
         f"workspace initialized at {ws.store.root}/.forage")
    return _hint(args, CLI_HINTS.get("init"))


def _cmd_ask(args, ws: Workspace) -> int:
    """Register an open question -> Workspace.ask."""
    q = ws.ask(args.text, args.uncertainty)
    _out(args, q, f"question {q['id']} registered (uncertainty: {q['uncertainty']})")
    return _hint(args, CLI_HINTS.get("ask"))


def _cmd_questions(args, ws: Workspace) -> int:
    """List or resolve questions -> Workspace.list_questions / update_question."""
    if args.action == "resolve":
        q = ws.update_question(args.qid, status="resolved")
        _out(args, q, f"{q['id']} resolved")
    else:
        qs = ws.list_questions()
        _out(args, qs, "\n".join(
            f"{q['id']}  [{q['status']}/{q['uncertainty']}]  {q['text']}" for q in qs)
            or "no questions yet - forage ask \"...\"")
    return _hint(args, CLI_HINTS.get("questions"))


def _cmd_search(args, ws: Workspace) -> int:
    """Search scholarly connectors -> Workspace.search."""
    r = ws.search(args.query, args.connector, args.limit)
    _out(args, r, f"{r['added']} sources added ({r['merged']} duplicates merged)")
    return _hint(args, CLI_HINTS.get("search"))


def _cmd_snowball(args, ws: Workspace) -> int:
    """Walk citations from a source -> Workspace.snowball."""
    r = ws.snowball(args.source_id, args.direction, args.budget)
    _out(args, r, f"{r['added']} sources added from citation graph")
    return _hint(args, CLI_HINTS.get("snowball"))


def _cmd_sources(args, ws: Workspace) -> int:
    """List/show sources or mark read -> Workspace.list_sources / get_source / mark_read."""
    if args.action == "mark":
        r = ws.mark_read(args.source_id, args.status or "read")
        _out(args, r, f"{r['source_id']} marked {r['read_status']}")
    elif args.action == "show":
        _out(args, ws.get_source(args.source_id))
    else:
        rows = ws.list_sources(read_status="unread" if args.unread else None,
                               limit=args.limit)
        _out(args, rows, "\n".join(
            f"{r['id']}  [{r['read_status']:7}] ({r['year'] or '????'}) {r['title'][:80]}"
            for r in rows) or "no sources yet - forage search \"...\"")
    return _hint(args, CLI_HINTS.get("sources"))


def _cmd_fetch_text(args, ws: Workspace) -> int:
    """Cache full text for a source -> Workspace.fetch_text."""
    r = ws.fetch_text(args.source_id)
    _out(args, r, f"{r['source_id']}: {r['text_status']} - {r['reason']}")
    return _hint(args, CLI_HINTS.get("fetch-text"))


def _cmd_text(args, ws: Workspace) -> int:
    """Read cached text / quote-snap -> Workspace.get_source_text / find_text (exit 2 on miss)."""
    if args.find:
        r = ws.find_text(args.source_id, args.find)
        if r.get("found"):
            _out(args, r, f"exact span (chars {r['start']}-{r['end']}, "
                          f"match {r['score']:.2f}):\n\"{r['text']}\"")
        else:
            _out(args, r, f"not found: {r['reason']}")
            return 2
    else:
        start, chars = 0, 2000
        if args.window:
            start, chars = (int(x) for x in args.window.split(":"))
        r = ws.get_source_text(args.source_id, start, chars)
        _out(args, r, r["text"] or "(no cached text)")
    return _hint(args, CLI_HINTS.get("text"))


def _cmd_pin(args, ws: Workspace) -> int:
    """Pin evidence to a source -> Workspace.pin."""
    r = ws.pin(args.source_id, quote=args.quote, find=args.find,
               locator=args.locator, note=args.note)
    _out(args, r, f"evidence {r['id']} pinned ({r['verification']})\n\"{r['quote']}\"")
    return _hint(args, CLI_HINTS.get("pin"))


def _cmd_claim(args, ws: Workspace) -> int:
    """Add a claim or link evidence -> Workspace.add_claim / link_evidence."""
    if args.action == "add":
        evidence = []
        for flag_value in (args.evidence or []):
            for part in flag_value.split(","):
                if not part:
                    continue
                ev_id, _, stance = part.partition(":")
                evidence.append((ev_id, stance or "supports"))
        c = ws.add_claim(args.text_or_id, evidence, args.confidence, args.question)
        _out(args, c, f"claim {c['id']} added (status: {c['status']})")
    else:
        if not args.evidence:
            raise ValueError("claim link requires --evidence EV_ID")
        c = ws.link_evidence(args.text_or_id, args.evidence[0].partition(":")[0],
                             args.stance or "supports")
        _out(args, c, f"claim {c['id']} now {c['status']}")
    return _hint(args, CLI_HINTS.get("claim"))


def _cmd_frontier(args, ws: Workspace) -> int:
    """Rank next-best reads by expected info gain -> Workspace.frontier."""
    r = ws.frontier(args.question, args.top)
    if args.json:
        _out(args, r)
    else:
        for i, row in enumerate(r["ranked"], 1):
            line = f"{i:2}. {row['score']:.3f}  {row['id']}  ({row['year'] or '????'}) {row['title'][:70]}"
            if args.explain:
                line += f"\n      {row['why']}"
            print(line)
        print(f"\npatch signal: {r['advice']}")
    return _hint(args, frontier_hint(r.get("patch_exhausted", False)))


def _cmd_brief(args, ws: Workspace) -> int:
    """Compile an uncertainty-aware brief -> Workspace.brief."""
    r = ws.brief(args.question_id, badge=not args.no_badge, out_path=args.out)
    if args.out:
        _out(args, r, f"brief written to {r['path']}: {r['claim_counts_by_status']}")
    else:
        print(r["markdown"])
    return _hint(args, CLI_HINTS.get("brief"))


def _cmd_audit(args, ws: Workspace) -> int:
    """Find unsupported/contested/degraded claims -> Workspace.audit (exit 3 on findings)."""
    r = ws.audit(refetch=args.refetch)
    if args.json:
        _out(args, r)
    else:
        if r["ok"]:
            print("audit clean: every claim supported and verified")
        for f in r["findings"]:
            print(f"[{f['kind']}] {f.get('claim') or f.get('evidence')}: {f['detail']}")
        print("\n" + audit_hint(r["ok"]))
    return 0 if r["ok"] else 3


def _cmd_status(args, ws: Workspace) -> int:
    """Workspace overview + patch signal -> Workspace.status."""
    r = ws.status()
    _out(args, r,
         f"questions {r['questions']} | sources {r['sources']} "
         f"({r['unread_sources']} unread) | evidence {r['evidence']} | "
         f"claims {r['claims']}\npatch signal: {r['advice']}")
    return _hint(args, CLI_HINTS.get("status"))


def _cmd_log(args, ws: Workspace) -> int:
    """Show ledger entries, optionally verify the hash chain -> Workspace.log (exit 4 if broken)."""
    r = ws.log(args.limit, args.verify)
    if args.json:
        _out(args, r)
    else:
        for e in r["entries"]:
            print(f"{e['ts']:.0f}  {e['actor']:24} {e['action']:16} {e['entity']}")
        if args.verify:
            print(f"chain: {'VERIFIED - ' + r['verify_message'] if r['verified'] else 'BROKEN - ' + r['verify_message']}")
            return 0 if r["verified"] else 4
    return _hint(args, CLI_HINTS.get("log"))


def _cmd_export(args, ws: Workspace) -> int:
    """Export sources -> Workspace.export."""
    text = ws.export(args.format)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"exported to {args.out}")
    else:
        print(text)
    return _hint(args, CLI_HINTS.get("export"))


def _cmd_serve(args, ws: Workspace) -> int:
    """Run the MCP stdio server -> mcp_server.serve (the agents' view of the same Workspace)."""
    from .mcp_server import serve
    serve(ws)
    return _hint(args, CLI_HINTS.get("serve"))


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse tree; each subparser binds its handler via set_defaults(func=...)."""
    p = argparse.ArgumentParser(
        prog="forage",
        description="Epistemic foraging: source discovery, evidence pinning, "
                    "uncertainty-aware briefs.")
    p.add_argument("--workspace", default=".", help="workspace directory")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="initialize a workspace")
    s.set_defaults(func=_cmd_init)

    s = sub.add_parser("ask", help="register an open question")
    s.add_argument("text")
    s.add_argument("--uncertainty", default="high", choices=["low", "med", "high"])
    s.set_defaults(func=_cmd_ask)

    s = sub.add_parser("questions", help="list or resolve questions")
    s.add_argument("action", nargs="?", default="list", choices=["list", "resolve"])
    s.add_argument("qid", nargs="?")
    s.set_defaults(func=_cmd_questions)

    s = sub.add_parser("search", help="search scholarly connectors")
    s.add_argument("query")
    s.add_argument("--connector", action="append", default=None,
                   choices=["openalex", "arxiv", "crossref"])
    s.add_argument("--limit", type=int, default=25)
    s.set_defaults(func=_cmd_search)

    s = sub.add_parser("snowball", help="walk citations from a source")
    s.add_argument("source_id")
    s.add_argument("--direction", default="both", choices=["back", "fwd", "both"])
    s.add_argument("--budget", type=int, default=40)
    s.set_defaults(func=_cmd_snowball)

    s = sub.add_parser("sources", help="list sources / mark read")
    s.add_argument("action", nargs="?", default="list", choices=["list", "show", "mark"])
    s.add_argument("source_id", nargs="?")
    s.add_argument("--unread", action="store_true")
    s.add_argument("--status", choices=["skimmed", "read"])
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=_cmd_sources)

    s = sub.add_parser("fetch-text", help="cache text for a source (OA registry only)")
    s.add_argument("source_id")
    s.set_defaults(func=_cmd_fetch_text)

    s = sub.add_parser("text", help="read cached text / quote-snap")
    s.add_argument("source_id")
    s.add_argument("--find", help="approximate text to locate exactly")
    s.add_argument("--window", help="START:CHARS")
    s.set_defaults(func=_cmd_text)

    s = sub.add_parser("pin", help="pin evidence to a source")
    s.add_argument("source_id")
    s.add_argument("--quote")
    s.add_argument("--find")
    s.add_argument("--loc", dest="locator")
    s.add_argument("--note")
    s.set_defaults(func=_cmd_pin)

    s = sub.add_parser("claim", help="add or link claims")
    s.add_argument("action", choices=["add", "link"])
    s.add_argument("text_or_id")
    s.add_argument("--evidence", action="append", default=None,
                   help="EV_ID[:STANCE],... — repeatable and/or comma-separated "
                        "(default stance: supports)")
    s.add_argument("--stance", choices=["supports", "contradicts", "mentions"])
    s.add_argument("--confidence", type=float)
    s.add_argument("--question", action="append")
    s.set_defaults(func=_cmd_claim)

    s = sub.add_parser("frontier", help="next-best reads by expected info gain")
    s.add_argument("--question")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--explain", action="store_true")
    s.set_defaults(func=_cmd_frontier)

    s = sub.add_parser("brief", help="compile an uncertainty-aware brief")
    s.add_argument("question_id")
    s.add_argument("--out")
    s.add_argument("--no-badge", action="store_true")
    s.set_defaults(func=_cmd_brief)

    s = sub.add_parser("audit", help="find unsupported/contested/degraded claims")
    s.add_argument("--refetch", action="store_true",
                   help="also re-fetch pinned sources and re-verify upstream (best-effort)")
    s.set_defaults(func=_cmd_audit)

    s = sub.add_parser("status", help="workspace overview + patch signal")
    s.set_defaults(func=_cmd_status)

    s = sub.add_parser("log", help="ledger entries")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--verify", action="store_true")
    s.set_defaults(func=_cmd_log)

    s = sub.add_parser("export", help="export sources")
    s.add_argument("--format", default="bibtex", choices=["bibtex"])
    s.add_argument("--out")
    s.set_defaults(func=_cmd_export)

    s = sub.add_parser("serve", help="run the MCP stdio server")
    s.add_argument("--mcp", action="store_true", default=True)
    s.set_defaults(func=_cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, open the Workspace, and run the selected command handler."""
    args = _build_parser().parse_args(argv)
    ws = Workspace(args.workspace)

    try:
        return args.func(args, ws)
    except (KeyError, ValueError, PermissionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
