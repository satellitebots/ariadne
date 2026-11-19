# Coding flow - the coordination a small planner cannot infer

## Shape of the work
1. Read the thing that fails first: the test, the error, the file the brief names. Read the tests that cover it.
2. Check whether the workspace already has work from an earlier run; a smoke test beats a rewrite.
3. Make the smallest change that does the job. Keep the existing style; do not reformat unrelated code.
4. Prove it with the repository's own tests, run from the workspace.
5. Commit locally with a one-line imperative message. Never push.

## Models
- **One agent model for the whole repository.** Every model switch costs a reload and a re-prefill and loses the
  conversation. Default: `qwen3.6-35b-a3b` (MoE, 3B active - much faster than the dense models on this GPU).
- Use `qwen3.8-27b` only for a step that is genuinely hard reasoning, and say in the step why it is worth the swap.
- Trivial steps (a commit, a directory) stay on the model already loaded.

## Tools
- `file` + `terminal` + `search`; the `git` MCP server for status/diff/commit; `memory` for what earlier tasks
  learned about this repository.
- Anything that may take more than a minute (installs, full test suites, builds, evals) is a **job**: write the
  script, `submit_job`, end the turn. Never run it in the terminal.
- Look up an API you have not seen in this workspace before using it (`web_search` → `web_fetch` of the official
  docs), and cite the URL in the step report.

## Gates
- Command gates run in the system shell from the workspace: write them so they work with the interpreter on PATH.
- Map every gate to the step that makes it pass, and make running it a step before the final one.
- Keep test output out of the tree (temp dirs, `.gitignore`) so a "clean tree" gate still holds afterwards.

## Do not
- Add deliverables the brief did not ask for (diagrams, docs, refactors).
- Plan a "think only" step whose result a later step on another model has to write down.
