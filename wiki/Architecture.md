# Architecture

Ariadne orchestrates; Hermes works. The orchestrator owns the drill, the state and every surface. The worker backend
is the pinned Hermes tree, imported/launched as-is and overlaid at module level when something must differ.

## Components

| Surface | What it is | Where |
|---|---|---|
| Console | FastAPI + a static ES-module SPA, no bundler | `ariadne/server/`, `ariadne/ui/` |
| Terminal | `python -m ariadne ...` | `ariadne/__main__.py` |
| Chat | a conversation bound to one session; submits, never works | `ariadne/chat.py` |
| MCP hosting | our task/server surface for Claude and other clients | `ariadne/tasks_mcp.py`, `ariadne/host.py` |
| Chat/worker state | sqlite task store, memory, session files | `.ariadne/` |

## The task path

```
you -> console / terminal / chat / MCP -> service.py -> tasks.db <- worker (detached)
                                                             |
                                                             +-> Hermes (pinned checkout, overlay) -> model server
                                                             +-> MCP servers (memory, jobs, web, git, browser,
                                                                  data, office, ci, rag, diagram, export, image, text)
                                                             +-> gates (shell commands, reviewers)
```

`service.py` owns every verb; `present.py` owns every rendering. A surface never touches `Store` and never formats a
task, so the doors cannot drift.

## Module map

- `orchestrator.py` - the worker process, the serve loop, the CLI. `worker.py` - planning, sign-off, execution,
  gates, retries, model chains, park, jobs. `store.py` - the store and the schema.
- `runtime/` - the **fallback** agent loop (model call, eight tools, MCP pool, skills reader, web search, trimming,
  logs, todo, park). Selected with `ARIADNE_RUNTIME=own`; the default is Hermes.
- `flows.py` - flow loading, validation, home compilation, `mcp_server_config`; `protocol.py` + `render.py` - the plan
  as data and its one renderer.
- `serving.py` + `resources.py` - where inference is and how much of the machine it may use; `models.py` +
  `modelindex.py` - the catalog and the hardware shortlist.
- `overlay.py` + `bootstrap.py` + `overlay.yaml` - the module overlay over `vendor/hermes`.
- `vendor/hermes/` - the pinned checkout. Never edited.

## The overlay

Import order is repo root, then `vendor/hermes`, then site-packages (`bootstrap.start()`). A module we own lives in
`overlay/<package>/<module>.py`; `overlay.apply()` prepends that package's `__path__` with the overlay directory, so
our file wins for that module and every other module still comes from the submodule. `overlay.yaml` records module,
reason and test; `overlay.check()` fails the suite on a missing one. Updates are a pointer bump plus
`uv sync --project vendor/hermes --frozen` - see `tools/sync_hermes.py`.

## State

`.ariadne/` holds everything: `tasks.db` (the store and events), `memory.db`, `logs/`, `homes/<flow>/` (compiled
flow homes, sessions, markers), `runtime-sessions/`, `park.json`, `limits.json`, `model-pins.json`, `servers.local.yaml`.
It is gitignored; nothing in it is required to read the code.
