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

## Distribution follow-ups (0.0.1 is published)

Done: README + `.mcp.json` + `.cursor/mcp.json` lead with `uvx foragekit`.

Still open (no PyPI account action needed — these are submissions):
- Submit `server.json` to the official MCP Registry (`mcp-publisher`), then
  the syndication list: awesome-mcp-servers PR (research category), mcp.so,
  Smithery, Glama.
- Set up the Trusted Publishing pending-publisher (see above) so `v0.0.2`
  onward publishes from a GitHub Release with no token.
- If the default branch is ever renamed, update the hero-image raw URL in
  README.md (it pins the current branch name so the image renders on PyPI).
