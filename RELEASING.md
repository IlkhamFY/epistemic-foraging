# Releasing foragekit

**0.0.1 is live: https://pypi.org/project/foragekit/** (first release published
manually with a scoped token). Subsequent releases should use **PyPI Trusted
Publishing** via the GitHub Release flow below — no API tokens, nothing to
store or rotate.

## One-time setup (~5 minutes, needs the PyPI account)

1. Log in to https://pypi.org → *Your account* → *Publishing* →
   *Add a new pending publisher* with exactly:
   - PyPI project name: `foragekit`
   - Owner: `IlkhamFY` · Repository: `epistemic-foraging`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. On GitHub: *Settings → Environments → New environment* named `pypi`
   (optionally add yourself as a required reviewer — that makes every publish
   a one-click approval).

## Every release after that

1. Bump `version` in `pyproject.toml` (and `serverInfo`/`server.json`).
2. Commit, push, then create a GitHub Release tagged `v<version>`
   (e.g. `v0.0.1`). The workflow builds, checks, and publishes.
3. Verify: `uvx foragekit serve --mcp` from any machine.

Manual fallback (if Actions is unavailable):
`pip install build twine && python -m build && twine upload dist/*`

## Distribution (state as of 0.0.2)

Done: README + `.mcp.json` + `.cursor/mcp.json` lead with `uvx foragekit`;
the README carries the registry ownership marker
(`mcp-name: io.github.ilkhamfy/foragekit`); `server.json` targets the
2025-12-11 registry schema; 0.0.2 adds the `foragekit` console-script alias
so `uvx foragekit serve --mcp` works as one word.

### MCP Registry — one click

Actions tab → **mcp-registry** → *Run workflow*. It authenticates with
GitHub OIDC (no tokens) and publishes `server.json`. Re-run after any
version bump (keep `server.json` versions in sync with `pyproject.toml`).

### awesome-mcp-servers — paste-ready PR line

Fork `punkpeye/awesome-mcp-servers`, add under the research/search category
(keep the list alphabetical), one-line entry:

```
- [IlkhamFY/epistemic-foraging](https://github.com/IlkhamFY/epistemic-foraging) 🐍 🏠 - Epistemic foraging for research agents: scholarly source discovery (OpenAlex/arXiv), machine-verified evidence pinning, uncertainty-aware briefs, hash-chained provenance ledger.
```

### Directories (web forms, ~2 min each)

mcp.so, Smithery, Glama: submit the GitHub URL + the description above;
install command `uvx foragekit serve --mcp`.

### Ongoing

- Set up the Trusted Publishing pending-publisher (top of this file) so
  future versions publish from a GitHub Release with no token.
- If the default branch is ever renamed, update the hero-image raw URL in
  README.md (it pins the current branch name so the image renders on PyPI).
