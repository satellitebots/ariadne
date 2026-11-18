---
name: coding-standards
description: Write code to published standards - look up the official docs before using a library or tool, follow the language's style and packaging guides, and prove it with linters, type checks and tests run as jobs.
---
# Coding standards

Your memory of an API can be out of date or wrong. The official docs are not. Write code the way the
language's and the library's own documentation says, and let tools, not your judgment, decide it is clean.

## Look it up first

Before you use a library, a CLI flag, a config format or a packaging field you have not already seen in this
workspace:
1. `web_search` for it, preferring the official site (the project's docs, docs.python.org, peps.python.org,
   packaging.python.org, PyPI).
2. `web_fetch` the page and read the part you need. Check the version: the docs for the version you pin.
3. Write a one-line source note where it matters (`# per https://... (v2.3)`) and list the URLs in the step report.
Do not copy code from blogs or Q&A sites when the official docs cover it.

## Python: the canonical sources

- Style: PEP 8 (peps.python.org/pep-0008); docstrings: PEP 257; type hints: PEP 484 and docs.python.org/3/library/typing.html.
- Project layout and metadata: packaging.python.org guides "Writing your pyproject.toml" and "src layout vs flat
  layout". Use `pyproject.toml` (PEP 621) with a `src/<package>/` layout, a `[project.optional-dependencies] dev`
  extra for the tools below, and pinned or lower-bounded versions you checked on PyPI.
- Lint and format: ruff (docs.astral.sh/ruff). Types: mypy (mypy.readthedocs.io), strict on new packages.
  Tests: pytest (docs.pytest.org). Security: bandit (bandit.readthedocs.io).
- Logging, not print, in library code (docs.python.org/3/howto/logging.html). CLIs with argparse or the library
  the project already uses.

## Write it

- Small modules with one job; public functions typed and documented; no bare `except:`; no global state.
- Network and disk at the edges, pure functions in the middle, so the middle is testable without the network.
- Tests do not touch the network: record fixtures (a small saved response) and test against those.
- Config in one place (pyproject or a settings module), never hard-coded paths or keys.

## Prove it (as jobs)

The gates are jobs (see the jobs skill), not terminal commands, and each writes a report file:
`python -m ruff check . && python -m ruff format --check . && python -m mypy src && python -m pytest -q`
with output saved under `reports/`. A step is done when the gates pass, not when the code looks right.
Fix what they report; do not silence a rule without a one-line reason next to it.
