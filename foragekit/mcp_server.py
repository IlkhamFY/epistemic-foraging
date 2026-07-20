"""Minimal MCP stdio server - zero dependencies, JSON-RPC 2.0 by hand.

Speaks enough of the Model Context Protocol for real clients (initialize,
tools/list, tools/call, ping). Writes are attributed in the ledger as
agent:<client name> per SPEC §5.1.
"""
from __future__ import annotations

import json
import sys

from .hints import INSTRUCTIONS, MCP_HINTS, audit_hint, frontier_hint
from .workspace import Workspace

PROTOCOL_VERSION = "2025-06-18"


def _tool(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": props, "required": required},
    }


_S = {"type": "string"}
_I = {"type": "integer"}
_N = {"type": "number"}

TOOLS = [
    _tool("forage_ask", "Register an open research question.",
          {"question": _S, "uncertainty": {**_S, "enum": ["low", "med", "high"]}}, ["question"]),
    _tool("forage_list_questions", "List questions with ids and status (start here when resuming).", {}, []),
    _tool("forage_update_question", "Resolve or re-grade a question.",
          {"question_id": _S, "status": _S, "uncertainty": _S, "note": _S}, ["question_id"]),
    _tool("forage_search", "Search scholarly connectors (openalex, arxiv, crossref).",
          {"query": _S, "connectors": {"type": "array", "items": _S}, "limit": _I}, ["query"]),
    _tool("forage_snowball", "Walk citations fwd/back from a source.",
          {"source_id": _S, "direction": {**_S, "enum": ["back", "fwd", "both"]}, "budget": _I},
          ["source_id"]),
    _tool("forage_list_sources", "Paginated compact source rows.",
          {"read_status": _S, "limit": _I, "offset": _I}, []),
    _tool("forage_get_source", "Full metadata for one source (no text).", {"source_id": _S}, ["source_id"]),
    _tool("forage_fetch_text", "Attempt text caching; reports tier and reason.", {"source_id": _S}, ["source_id"]),
    _tool("forage_get_source_text", "Windowed canonical text (auto-advances unread to skimmed).",
          {"source_id": _S, "start": _I, "max_chars": _I}, ["source_id"]),
    _tool("forage_find_text", "Quote-snap: approximate wording in, exact pin-ready span out.",
          {"source_id": _S, "query": _S}, ["source_id", "query"]),
    _tool("forage_mark_read", "Mark a source skimmed or read.",
          {"source_id": _S, "status": {**_S, "enum": ["skimmed", "read"]}}, ["source_id", "status"]),
    _tool("forage_pin_evidence", "Pin a verbatim quote (canonical-match verified).",
          {"source_id": _S, "quote": _S, "find": _S, "locator": _S, "note": _S}, ["source_id"]),
    _tool("forage_add_claim", "Add a claim with stance-bearing evidence links.",
          {"text": _S, "evidence": {"type": "array", "items": {
              "type": "object", "properties": {"evidence_id": _S, "stance": _S},
              "required": ["evidence_id"]}},
           "confidence": _N, "questions": {"type": "array", "items": _S}}, ["text"]),
    _tool("forage_link_evidence", "Attach (possibly contradicting) evidence to a claim.",
          {"claim_id": _S, "evidence_id": _S, "stance": {**_S, "enum": ["supports", "contradicts", "mentions"]}},
          ["claim_id", "evidence_id", "stance"]),
    _tool("forage_get_claim", "Claim with links and derived status.", {"claim_id": _S}, ["claim_id"]),
    _tool("forage_get_evidence", "One evidence pin.", {"evidence_id": _S}, ["evidence_id"]),
    _tool("forage_frontier", "Next-best reads by expected info gain, with patch_exhausted signal.",
          {"question_id": _S, "top": _I}, []),
    _tool("forage_status", "Workspace overview + patch-yield signal.", {}, []),
    _tool("forage_brief", "Compile the brief; with out_path returns only a summary.",
          {"question_id": _S, "out_path": _S, "badge": {"type": "boolean"}}, ["question_id"]),
    _tool("forage_audit", "Machine-readable findings (unsupported/contested/degraded).",
          {"refetch": {"type": "boolean",
                       "description": "also re-verify pins against re-fetched upstream text"}}, []),
    _tool("forage_log", "Recent ledger entries.", {"limit": _I, "verify": {"type": "boolean"}}, []),
]


def _call(ws: Workspace, name: str, a: dict):
    if name == "forage_ask":
        return ws.ask(a["question"], a.get("uncertainty", "high"))
    if name == "forage_list_questions":
        return ws.list_questions()
    if name == "forage_update_question":
        return ws.update_question(a["question_id"], a.get("status"),
                                  a.get("uncertainty"), a.get("note"))
    if name == "forage_search":
        return ws.search(a["query"], a.get("connectors"), a.get("limit", 25))
    if name == "forage_snowball":
        return ws.snowball(a["source_id"], a.get("direction", "both"), a.get("budget", 40))
    if name == "forage_list_sources":
        return ws.list_sources(a.get("read_status"), a.get("limit", 50), a.get("offset", 0))
    if name == "forage_get_source":
        return ws.get_source(a["source_id"])
    if name == "forage_fetch_text":
        return ws.fetch_text(a["source_id"])
    if name == "forage_get_source_text":
        return ws.get_source_text(a["source_id"], a.get("start", 0), a.get("max_chars", 2000))
    if name == "forage_find_text":
        return ws.find_text(a["source_id"], a["query"])
    if name == "forage_mark_read":
        return ws.mark_read(a["source_id"], a["status"])
    if name == "forage_pin_evidence":
        return ws.pin(a["source_id"], quote=a.get("quote"), find=a.get("find"),
                      locator=a.get("locator"), note=a.get("note"))
    if name == "forage_add_claim":
        ev = [(e["evidence_id"], e.get("stance", "supports")) for e in a.get("evidence", [])]
        return ws.add_claim(a["text"], ev, a.get("confidence"), a.get("questions"))
    if name == "forage_link_evidence":
        return ws.link_evidence(a["claim_id"], a["evidence_id"], a["stance"])
    if name == "forage_get_claim":
        return ws.get_claim(a["claim_id"])
    if name == "forage_get_evidence":
        return ws.get_evidence(a["evidence_id"])
    if name == "forage_frontier":
        return ws.frontier(a.get("question_id"), a.get("top", 10))
    if name == "forage_status":
        return ws.status()
    if name == "forage_brief":
        return ws.brief(a["question_id"], badge=a.get("badge", True),
                        out_path=a.get("out_path"))
    if name == "forage_audit":
        return ws.audit(refetch=a.get("refetch", False))
    if name == "forage_log":
        return ws.log(a.get("limit", 20), a.get("verify", False))
    raise KeyError(f"unknown tool {name}")


def serve(ws: Workspace):  # pragma: no cover - exercised by integration test
    def reply(msg_id, result=None, error=None):
        out: dict = {"jsonrpc": "2.0", "id": msg_id}
        if error is not None:
            out["error"] = error
        else:
            out["result"] = result
        sys.stdout.write(json.dumps(out, default=str) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, msg_id = msg.get("method"), msg.get("id")
        if method == "initialize":
            client = (msg.get("params", {}).get("clientInfo") or {}).get("name", "mcp-client")
            ws.actor = f"agent:{client}"
            reply(msg_id, {
                "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "foragekit", "version": "0.0.2"},
                "instructions": INSTRUCTIONS,
            })
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            reply(msg_id, {})
        elif method == "tools/list":
            reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params", {})
            try:
                name = params.get("name", "")
                result = _call(ws, name, params.get("arguments") or {})
                if name == "forage_frontier":
                    hint = frontier_hint(result.get("patch_exhausted", False), mcp=True)
                elif name == "forage_audit":
                    hint = audit_hint(result.get("ok", False), mcp=True)
                else:
                    hint = MCP_HINTS.get(name)
                if hint:
                    if isinstance(result, dict):
                        result = {**result, "next": hint}
                    else:
                        result = {"items": result, "next": hint}
                reply(msg_id, {"content": [{"type": "text",
                                            "text": json.dumps(result, default=str)}],
                               "isError": False})
            except Exception as e:
                reply(msg_id, {"content": [{"type": "text", "text": f"error: {e}"}],
                               "isError": True})
        elif msg_id is not None:
            reply(msg_id, error={"code": -32601, "message": f"method {method} not supported"})
