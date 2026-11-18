---
name: planning-lessons
description: How to write a coding plan the local worker can execute - steps that leave files, few model switches, every gate mapped, gates runnable where QA runs them.
---
# Planning lessons

From reviews of backbriefs and runs during validation (todo app, RAG design).

## Steps
- Every step leaves its output in files. Steps on different models run in separate sessions that only get a
  summary of earlier steps, so never plan a "think only" step whose result another model has to write down.
- Switch models only where it clearly pays: a swap costs a reload and a prefill. Trivial steps (mkdir, git
  commit) stay on the model already loaded. One codebase or one document is one model by default; a plan
  that hops between models (RAG build: 3 models, 5 switches) gets overridden to a single model at sign-off.
- When the workspace already has work from an earlier run, start by checking it (smoke test) instead of
  rewriting it.

- Order steps so evidence comes after the run that produces it: run the real command (ingest, ask, eval)
  first, then write the README section that quotes its output. Never plan documentation of results before
  the step that creates them.
- Stay inside the brief: no extra deliverables (e.g. rendering diagrams in a coding task that did not ask for
  them).

## Gates
- Map every gate to the step that makes it pass, and add the check itself as a step (run the tests, render the
  diagrams) before the final one.
- Command gates run in the system shell from the workspace, with the `python` found on PATH - not necessarily
  the interpreter you used. Before finishing, run each gate command exactly as written in that shell; if a tool
  it needs is missing there (e.g. `No module named pytest`), install it for that interpreter
  (`python -m pip install pytest`) and say so in the report. (Todo app: three QA rounds were spent on this.)
- Keep test runs from dirtying the tree: temp dirs for test data, a .gitignore for caches and outputs, so a
  "clean working tree" gate holds after the tests ran.
