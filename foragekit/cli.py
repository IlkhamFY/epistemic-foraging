"""The forage CLI. Every command supports --json; exit codes are stable."""
from __future__ import annotations

import argparse
import json
import sys

from .hints import CLI_HINTS, audit_hint, frontier_hint
from .workspace import Workspace


def _out(args, data, human: str | None = None):
    if getattr(args, "json", False) or human is None:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(human)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="forage",
        description="Epistemic foraging: source discovery, evidence pinning, "
                    "uncertainty-aware briefs.")
    p.add_argument("--workspace", default=".", help="workspace directory")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="initialize a workspace")

    s = sub.add_parser("ask", help="register an open question")
    s.add_argument("text")
    s.add_argument("--uncertainty", default="high", choices=["low", "med", "high"])

    s = sub.add_parser("questions", help="list or resolve questions")
    s.add_argument("action", nargs="?", default="list", choices=["list", "resolve"])
    s.add_argument("qid", nargs="?")

    s = sub.add_parser("search", help="search scholarly connectors")
    s.add_argument("query")
    s.add_argument("--connector", action="append", default=None,
                   choices=["openalex", "arxiv", "crossref"])
    s.add_argument("--limit", type=int, default=25)

    s = sub.add_parser("snowball", help="walk citations from a source")
    s.add_argument("source_id")
    s.add_argument("--direction", default="both", choices=["back", "fwd", "both"])
    s.add_argument("--budget", type=int, default=40)

    s = sub.add_parser("sources", help="list sources / mark read")
    s.add_argument("action", nargs="?", default="list", choices=["list", "show", "mark"])
    s.add_argument("source_id", nargs="?")
    s.add_argument("--unread", action="store_true")
    s.add_argument("--status", choices=["skimmed", "read"])
    s.add_argument("--limit", type=int, default=50)

    s = sub.add_parser("fetch-text", help="cache text for a source (OA registry only)")
    s.add_argument("source_id")

    s = sub.add_parser("text", help="read cached text / quote-snap")
    s.add_argument("source_id")
    s.add_argument("--find", help="approximate text to locate exactly")
    s.add_argument("--window", help="START:CHARS")

    s = sub.add_parser("pin", help="pin evidence to a source")
    s.add_argument("source_id")
    s.add_argument("--quote")
    s.add_argument("--find")
    s.add_argument("--loc", dest="locator")
    s.add_argument("--note")

    s = sub.add_parser("claim", help="add or link claims")
    s.add_argument("action", choices=["add", "link"])
    s.add_argument("text_or_id")
    s.add_argument("--evidence", action="append", default=None,
                   help="EV_ID[:STANCE],... — repeatable and/or comma-separated "
                        "(default stance: supports)")
    s.add_argument("--stance", choices=["supports", "contradicts", "mentions"])
    s.add_argument("--confidence", type=float)
    s.add_argument("--question", action="append")

    s = sub.add_parser("frontier", help="next-best reads by expected info gain")
    s.add_argument("--question")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--explain", action="store_true")

    s = sub.add_parser("brief", help="compile an uncertainty-aware brief")
    s.add_argument("question_id")
    s.add_argument("--out")
    s.add_argument("--no-badge", action="store_true")

    sub.add_parser("audit", help="find unsupported/contested/degraded claims")
    sub.add_parser("status", help="workspace overview + patch signal")

    s = sub.add_parser("log", help="ledger entries")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--verify", action="store_true")

    s = sub.add_parser("export", help="export sources")
    s.add_argument("--format", default="bibtex", choices=["bibtex"])
    s.add_argument("--out")

    s = sub.add_parser("serve", help="run the MCP stdio server")
    s.add_argument("--mcp", action="store_true", default=True)

    args = p.parse_args(argv)
    ws = Workspace(args.workspace)

    try:
        return _dispatch(args, ws)
    except (KeyError, ValueError, PermissionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _dispatch(args, ws: Workspace) -> int:
    if args.cmd == "init":
        _out(args, {"workspace": str(ws.store.root)},
             f"workspace initialized at {ws.store.root}/.forage")
    elif args.cmd == "ask":
        q = ws.ask(args.text, args.uncertainty)
        _out(args, q, f"question {q['id']} registered (uncertainty: {q['uncertainty']})")
    elif args.cmd == "questions":
        if args.action == "resolve":
            q = ws.update_question(args.qid, status="resolved")
            _out(args, q, f"{q['id']} resolved")
        else:
            qs = ws.list_questions()
            _out(args, qs, "\n".join(
                f"{q['id']}  [{q['status']}/{q['uncertainty']}]  {q['text']}" for q in qs)
                or "no questions yet - forage ask \"...\"")
    elif args.cmd == "search":
        r = ws.search(args.query, args.connector, args.limit)
        _out(args, r, f"{r['added']} sources added ({r['merged']} duplicates merged)")
    elif args.cmd == "snowball":
        r = ws.snowball(args.source_id, args.direction, args.budget)
        _out(args, r, f"{r['added']} sources added from citation graph")
    elif args.cmd == "sources":
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
    elif args.cmd == "fetch-text":
        r = ws.fetch_text(args.source_id)
        _out(args, r, f"{r['source_id']}: {r['text_status']} - {r['reason']}")
    elif args.cmd == "text":
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
    elif args.cmd == "pin":
        r = ws.pin(args.source_id, quote=args.quote, find=args.find,
                   locator=args.locator, note=args.note)
        _out(args, r, f"evidence {r['id']} pinned ({r['verification']})\n\"{r['quote']}\"")
    elif args.cmd == "claim":
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
    elif args.cmd == "frontier":
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
    elif args.cmd == "brief":
        r = ws.brief(args.question_id, badge=not args.no_badge, out_path=args.out)
        if args.out:
            _out(args, r, f"brief written to {r['path']}: {r['claim_counts_by_status']}")
        else:
            print(r["markdown"])
    elif args.cmd == "audit":
        r = ws.audit()
        if args.json:
            _out(args, r)
        else:
            if r["ok"]:
                print("audit clean: every claim supported and verified")
            for f in r["findings"]:
                print(f"[{f['kind']}] {f.get('claim') or f.get('evidence')}: {f['detail']}")
            print("\n" + audit_hint(r["ok"]))
        return 0 if r["ok"] else 3
    elif args.cmd == "status":
        r = ws.status()
        _out(args, r,
             f"questions {r['questions']} | sources {r['sources']} "
             f"({r['unread_sources']} unread) | evidence {r['evidence']} | "
             f"claims {r['claims']}\npatch signal: {r['advice']}")
    elif args.cmd == "log":
        r = ws.log(args.limit, args.verify)
        if args.json:
            _out(args, r)
        else:
            for e in r["entries"]:
                print(f"{e['ts']:.0f}  {e['actor']:24} {e['action']:16} {e['entity']}")
            if args.verify:
                print(f"chain: {'VERIFIED - ' + r['verify_message'] if r['verified'] else 'BROKEN - ' + r['verify_message']}")
                return 0 if r["verified"] else 4
    elif args.cmd == "export":
        text = ws.export(args.format)
        if args.out:
            with open(args.out, "w") as fh:
                fh.write(text)
            print(f"exported to {args.out}")
        else:
            print(text)
    elif args.cmd == "serve":
        from .mcp_server import serve
        serve(ws)
    if not getattr(args, "json", False):
        if args.cmd == "frontier":
            print("\n" + frontier_hint(r.get("patch_exhausted", False)))
        elif CLI_HINTS.get(args.cmd):
            print("\n" + CLI_HINTS[args.cmd])
    return 0


if __name__ == "__main__":
    sys.exit(main())
