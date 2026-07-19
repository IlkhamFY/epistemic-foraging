# Releasing foragekit

The package is release-ready: `python -m build` and `twine check` both pass,
and the `foragekit` name is unclaimed on PyPI (verified 2026-07). Publishing
uses **PyPI Trusted Publishing** — no API tokens ever exist.

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

## After the first publish (unlocks distribution)

- Flip the README install block to lead with `uvx foragekit serve --mcp` and
  update `.mcp.json` / `.cursor/mcp.json` to use `uvx` instead of the local
  `python3 -m foragekit.cli`.
- Submit `server.json` to the official MCP Registry (`mcp-publisher`), then
  the syndication list: awesome-mcp-servers PR (research category), mcp.so,
  Smithery, Glama.
- If the default branch is ever renamed, update the hero-image raw URL in
  README.md (it pins the current branch name so the image renders on PyPI).
