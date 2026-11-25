# Conventions: the one format for docs, code and commits

Ariadne has nine authority documents and they must not disagree. This file is the rule for how they are written and
which one wins.

## Authority order (the current truth)

1. `docs/CONVENTIONS.md` - this file: format and authority.
2. `docs/DESIGN.md` - the model (front, orchestrator, task/run, worker, broker, flows) and the order of work.
3. `docs/BACKLOG.md` - the queue and its history; an item is done only when it says so here.
4. `docs/MODELS.md`, `docs/MCP.md`, `docs/COVERAGE.md`, `docs/FRONTEND.md`, `docs/UI-DIRECTION.md` - per-topic;
   where one disagrees with `DESIGN.md`, `DESIGN.md` wins until the topic doc is updated.
5. Superseded, and marked as such at their top: `docs/GAP-ANALYSIS.md`, `docs/FORK.md`, `docs/DESIGN-RESET.md`.

Current position, stated once (details in `DESIGN.md`): **one front** (MCP, UI and chat over the same verbs, MCP
also the bypass for an outside orchestrator); a **local orchestrator** that defines durable tasks and never works;
**Hermes is the worker** (`vendor/hermes` submodule, overlaid, never edited directly), one headless run per step;
a **broker** that alone owns the model server and hands the machine over at step boundaries; **flows** are task
templates. The own runtime (`ariadne/runtime/`) runs only the orchestrator conversation.

## Document format

- A doc either is current or carries a `> **Superseded in part (date, by what).**` banner as its first line after
  the title. A conflicted doc without a banner is a bug.
- Every claim about the code names the file (or the test) that makes it true; prefer counts to adjectives.
- Status words come from `ariadne/present.py::STATUS` only. No surface invents a label.

## Code rules

- `service.py` owns every verb and every rule; `present.py` owns every rendering. No surface touches `Store` or
  formats a task itself.
- Behaviour changes land with a test; `pytest -q` passes before any commit.
- Never edit `vendor/` or `overlay/` without an explicit instruction and a test that pins the override.
- Line endings: LF in the index (`.gitattributes`); the file `docs/BACKLOG.md` said "strong engineering principles"
  - this file is them.
- Commit messages: `area: sentence` first line, body only when the why is not obvious, and they never claim a state
  the suite did not verify.
