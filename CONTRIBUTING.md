# Contributing to foragekit

Thanks for foraging with us. Ground rules, short version:

- **Connectors are the designed first contribution.** A connector must pass
  the conformance rules in [SPEC §2.1](docs/SPEC.md#21-source-discovery):
  static host declaration, polite rate limiting, honest User-Agent,
  works-and-citations surface only. Its hosts must be a public scholarly API.
- **Scope is enforced.** PRs that add capabilities under
  [SPEC §8 non-goals](docs/SPEC.md#8-non-goals-permanent) — generic URL
  fetching, person-centric features, offensive-security / biosafety /
  persuasion workflows — are closed with a pointer to that section, however
  well-implemented they are.
- **Tests are offline.** `python -m pytest tests/ -q` must pass without
  network access; connector tests use recorded fixtures, never live APIs.
- **Zero dependencies is a feature.** Adding a runtime dependency needs a
  strong argument in the PR description.
- Keep the README under ~2,000 words; depth goes to `docs/SPEC.md`.

Wanted (good first issues): Crossref and Semantic Scholar connectors,
Zotero/CSL-JSON export adapters, brief output formats, README translations.
