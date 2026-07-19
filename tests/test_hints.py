"""The server must teach the agent: handshake instructions + next hints."""
import json
import subprocess
import sys


def _mcp(tmp_path, messages):
    proc = subprocess.Popen(
        [sys.executable, "-m", "foragekit.cli", "serve"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=tmp_path)
    out, _ = proc.communicate(
        "\n".join(json.dumps(m) for m in messages) + "\n", timeout=30)
    return [json.loads(l) for l in out.strip().split("\n")]


def test_initialize_carries_loop_instructions(tmp_path):
    replies = _mcp(tmp_path, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"clientInfo": {"name": "t"}}}])
    instructions = replies[0]["result"]["instructions"]
    assert "THE LOOP" in instructions
    assert "No pin, no claim" in instructions
    assert "patch_exhausted" in instructions


def test_tool_results_carry_next_hint(tmp_path):
    replies = _mcp(tmp_path, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"clientInfo": {"name": "t"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "forage_ask", "arguments": {"question": "q?"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "forage_list_questions", "arguments": {}}},
    ])
    ask = json.loads(replies[1]["result"]["content"][0]["text"])
    assert ask["next"].startswith("next: forage_search")
    listed = json.loads(replies[2]["result"]["content"][0]["text"])
    assert "items" in listed and "next" in listed  # lists get wrapped


def test_cli_prints_hint_in_human_mode_only(tmp_path):
    subprocess.run([sys.executable, "-m", "foragekit.cli", "init"],
                   cwd=tmp_path, check=True, capture_output=True)
    human = subprocess.run(
        [sys.executable, "-m", "foragekit.cli", "ask", "q?"],
        cwd=tmp_path, capture_output=True, text=True)
    assert "next: forage search" in human.stdout
    machine = subprocess.run(
        [sys.executable, "-m", "foragekit.cli", "--json", "ask", "q2?"],
        cwd=tmp_path, capture_output=True, text=True)
    assert "next:" not in machine.stdout  # --json stays pure data
