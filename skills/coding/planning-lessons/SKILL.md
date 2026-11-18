---
name: planning-lessons
description: How to write a plan the local worker can execute - steps that leave files, few model switches, every gate mapped.
---
# Planning lessons

From reviews of backbriefs during validation (todo app, RAG design).

- Every step leaves its output in files. Steps on different models run in separate sessions that only get a
  summary of earlier steps, so never plan a "think only" step whose result another model has to write down.
- Switch models only where it clearly pays: a model swap costs a reload and a prefill. A trivial step (mkdir,
  git commit) stays on the model already loaded.
- Map every gate to the step that makes it pass, and add the check itself as a step (run the tests, render the
  diagrams) before the final one.
- When the workspace already has work from an earlier run, start by checking it (smoke test) instead of
  rewriting it.
- Keep test runs from dirtying the tree: temp dirs for test data, a .gitignore for caches and outputs.
