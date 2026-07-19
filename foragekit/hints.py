"""The server teaches the agent.

Two mechanisms: loop INSTRUCTIONS injected via the MCP initialize handshake
(clients surface them to the model automatically), and a one-line `next` hint
on every tool/command response so the workflow stays self-propelling even
after the handshake has scrolled out of the agent's attention.
"""

INSTRUCTIONS = """foragekit makes you an epistemic forager: reduce uncertainty about open questions, with receipts. THE LOOP:
1. forage_ask the research question first (forage_list_questions when resuming).
2. forage_search 2-3 differently-worded queries, then forage_snowball from the 1-2 best hits - citation walks find what keywords miss.
3. Read in forage_frontier order, not list order. Read via forage_get_source_text windows; forage_mark_read afterwards. When frontier says patch_exhausted, believe it: switch queries or clusters.
4. No pin, no claim: for every finding, forage_find_text with approximate wording, then forage_pin_evidence with the exact span it returns. Never paraphrase inside a pin.
5. forage_add_claim with explicit stances; record disagreement as contradicts - contested claims are a finding, not a failure. State confidence as your real credence.
6. forage_audit and fix what it flags, then forage_brief (use out_path) and forage_update_question to resolve.
Everything you do is recorded in a hash-chained ledger under your client name; work as if the human will replay it, because they can."""

MCP_HINTS = {
    "forage_ask": "next: forage_search 2-3 differently-worded queries",
    "forage_list_questions": "next: forage_status for workspace state, forage_frontier for what to read",
    "forage_search": "next: forage_frontier to rank reads; forage_snowball a strong hit to grow the pool",
    "forage_snowball": "next: forage_frontier to re-rank the grown pool",
    "forage_list_sources": "next: forage_get_source_text to read one; forage_frontier to pick which",
    "forage_get_source": "next: forage_get_source_text to read it in windows",
    "forage_fetch_text": "next: forage_get_source_text to read; forage_find_text to locate pin-worthy spans",
    "forage_get_source_text": "next: forage_find_text + forage_pin_evidence for anything worth keeping; forage_mark_read when done",
    "forage_find_text": "next: forage_pin_evidence with this exact span",
    "forage_pin_evidence": "next: forage_add_claim citing this evidence id (stance contradicts if it disagrees with a claim)",
    "forage_mark_read": "next: forage_frontier for the next best read",
    "forage_add_claim": "next: strengthen with more evidence via forage_link_evidence, or forage_audit when the claim set feels complete",
    "forage_link_evidence": "next: forage_audit to check the claim set",
    "forage_brief": "next: forage_update_question to resolve/re-grade; forage_log verify=true for the audit trail",
    "forage_update_question": "next: forage_log verify=true proves the trail; done",
}

CLI_HINTS = {
    "init": "next: forage ask \"<your research question>\"",
    "ask": "next: forage search \"<query>\" (2-3 differently-worded searches, then snowball a strong hit)",
    "search": "next: forage frontier --top 8 to rank reads; forage snowball <src_id> to grow the pool",
    "snowball": "next: forage frontier --top 8 to re-rank the grown pool",
    "fetch-text": "next: forage text <src_id> --window 0:1200 to read it",
    "text": ("next: forage pin <src_id> --find \"<approx words>\" for anything worth "
             "keeping; forage sources mark <src_id> --status read when done"),
    "pin": "next: forage claim add \"<claim>\" --evidence <ev_id>:supports --question <q_id> (:contradicts for disagreement)",
    "claim": "next: more pins strengthen it; forage audit when the claim set feels complete",
    "brief": "next: forage questions resolve <q_id>; forage log --verify proves the trail",
}


def frontier_hint(patch_exhausted: bool, mcp: bool = False) -> str:
    if patch_exhausted:
        return ("next: this patch is exhausted - try a new differently-worded search "
                "or snowball an unread cluster")
    if mcp:
        return ("next: forage_get_source_text the top hit, pin what matters, "
                "forage_mark_read, repeat")
    return ("next: forage text <top_src_id> --window 0:1200, pin what matters, "
            "forage sources mark <src_id> --status read, repeat")


def audit_hint(ok: bool, mcp: bool = False) -> str:
    if ok:
        return ("next: compile with forage_brief (out_path recommended)" if mcp
                else "next: forage brief <q_id> --out brief.md")
    return ("next: fix findings (add evidence to unsupported claims, link stances), "
            "then re-run audit before compiling the brief")
