"""Build a foraging agent in ~30 lines with the Claude Agent SDK.

The third on-ramp (after Claude Code and the CLI): drive foragekit from your
own Python program. Note what is MISSING here — no skill text, no loop
instructions. The foragekit MCP server teaches the agent the foraging loop
through its initialize handshake and per-tool `next` hints, so the system
prompt only has to say what to produce, not how to research.

    pip install claude-agent-sdk foragekit
    python examples/foraging_agent.py "Does spaced repetition beat cramming?"
"""
import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

WORKSPACE = Path("./forage-workspace")


async def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else (
        "Do retrieval-augmented LLMs hallucinate less than closed-book LLMs?")
    WORKSPACE.mkdir(exist_ok=True)

    options = ClaudeAgentOptions(
        mcp_servers={
            "forage": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "foragekit.cli", "serve"],
                "env": {"FORAGE_ACTOR": "agent:sdk-example"},
            }
        },
        # Auto-approve only the foraging tools - the agent needs nothing else.
        allowed_tools=[
            "mcp__forage__forage_ask", "mcp__forage__forage_list_questions",
            "mcp__forage__forage_update_question", "mcp__forage__forage_search",
            "mcp__forage__forage_snowball", "mcp__forage__forage_list_sources",
            "mcp__forage__forage_get_source", "mcp__forage__forage_fetch_text",
            "mcp__forage__forage_get_source_text", "mcp__forage__forage_find_text",
            "mcp__forage__forage_mark_read", "mcp__forage__forage_pin_evidence",
            "mcp__forage__forage_add_claim", "mcp__forage__forage_link_evidence",
            "mcp__forage__forage_get_claim", "mcp__forage__forage_get_evidence",
            "mcp__forage__forage_frontier", "mcp__forage__forage_status",
            "mcp__forage__forage_brief", "mcp__forage__forage_audit",
            "mcp__forage__forage_log",
        ],
        system_prompt=(
            "You are a research agent. Research the user's question using only "
            "the forage tools, then compile the brief to brief.md (use out_path) "
            "and finish with a 3-sentence summary of what the evidence shows."
        ),
        permission_mode="dontAsk",   # nothing outside allowed_tools ever runs
        cwd=str(WORKSPACE),          # the .forage workspace auto-initializes here
        max_turns=60,
    )

    async for message in query(prompt=question, options=options):
        # Print assistant text as it arrives; tool traffic stays quiet.
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    print(block.text)
        elif isinstance(message, ResultMessage):
            print(f"\n[done: {message.num_turns} turns, "
                  f"${message.total_cost_usd or 0:.2f}]")

    brief = WORKSPACE / "brief.md"
    if brief.exists():
        print(f"\n--- brief written to {brief} "
              f"({sum(1 for _ in brief.open())} lines) ---")
        print("verify the trail:  cd forage-workspace && forage log --verify")


if __name__ == "__main__":
    asyncio.run(main())
