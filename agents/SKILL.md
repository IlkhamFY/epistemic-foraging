# Skill: epistemic foraging with foragekit

Drop-in instructions for any AI agent connected to the foragekit MCP server
(`uvx foragekit serve --mcp`). Paste this into your agent's instructions, or
install it as a skill. It teaches the loop; the tools enforce the rules.

## The loop

1. **Register the question first.** Call `forage_ask` with the user's research
   question before searching anything. Every later step is prioritized against
   open questions. Resuming an old workspace? Start with
   `forage_list_questions` to recover ids and state.
2. **Search wide, then snowball.** Use `forage_search` for 1–2 broad queries,
   then `forage_snowball` from the most central results instead of endlessly
   rephrasing keywords — citation walks find what keyword search can't.
3. **Read by expected information gain, not list order.** Call
   `forage_frontier` and read what it ranks highest — it balances relevance,
   novelty, and centrality against reading cost. When the response says
   `patch_exhausted`, believe it: switch queries or clusters instead of
   grinding a dead patch.
4. **Fetch, then read in windows.** `forage_fetch_text` caches full text when
   licensing allows (it reports why when it can't). Read with
   `forage_get_source_text` windows — never try to hold a whole paper in
   context. Mark what you've processed with `forage_mark_read`.
5. **Pin before you claim.** Never state a finding without evidence. Use
   `forage_find_text` with approximate wording to get the exact span and
   locator, then `forage_pin_evidence`. Pins are verification-tiered
   (full-text / abstract / unverified) — prefer the strongest tier available.
6. **Claim with honest stance and confidence.** `forage_add_claim` links
   evidence with explicit stances — record `contradicts` links when sources
   disagree; contested claims are a finding, not a failure. State confidence
   as your actual credence, not politeness (it is author-stated and audited
   later, not decoration).
7. **Audit before you present.** Run `forage_audit` and fix what it flags —
   unsupported claims, single-source claims, stale pins — before compiling.
8. **Compile the brief to a file.** `forage_brief` with `out_path` writes the
   self-contained artifact and returns only a summary, keeping your context
   clean. Then `forage_update_question` to resolve or re-grade the question.

## Rules of the workspace

- No pin, no claim. If you can't find a span to pin, say the claim is
  unsupported — the audit will catch it anyway.
- Quote exactly what `forage_find_text` returns; never paraphrase inside a pin.
- One question per `forage_ask`; split compound questions.
- Everything you do is recorded in a hash-chained ledger under your client
  name. Work as if the human will replay it — because they can.

## Scope

foragekit is for literature review and knowledge work only. It will not fetch
arbitrary URLs, resolve people, or support recon, biosafety, or persuasion
workflows — don't try to bend it; see SPEC §8 in the repo.
