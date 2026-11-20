# Architecture

Ariadne orchestrates (the drill, the store, gates, sessions, the busy gate). Hermes is the worker backend: a pinned git submodule at `vendor/hermes`, overlaid at module level, never edited directly. Ariadne owns its React UI, its chat, and its MCP-hosting surface. The small runtime runner (`ariadne/runtime/`) is the model-free fallback, selectable with `ARIADNE_RUNTIME=own`.

## Components

| Surface | What it is | Where |
|---|---|---|
| Console | React + Vite + TS SPA, served by FastAPI | `ariadne/server/`, `ariadne/ui/` |
| Terminal | `python -m ariadne ...` | `ariadne/__main__.py` |
| Chat | A conversation bound to one session; submits tasks, never does the work | `ariadne/chat.py` |
| MCP hosting | Ariadne's task/server surface for Claude and other MCP clients | `ariadne/tasks_mcp.py`, `ariadne/host.py` |
| Worker | Planning, sign-off, execution, gates, retries, model chains, park, jobs | `ariadne/worker.py` |
| Runtime fallback | Model-free agent loop (tools, MCP pool, skills, web, trimming, logs) | `ariadne/runtime/` |
| Chat/worker state | SQLite task store, memory, session files | `.ariadne/` |

## The task path

```
you -> console / terminal / chat / MCP -> service.py -> tasks.db <- worker (detached)
                                                             |
                                                             +-> Hermes (pinned checkout, overlay) -> model server
                                                             +-> MCP servers (per-step, scoped by flow)
                                                             +-> gates (shell commands, reviewers)
```

`service.py` owns every verb; `present.py` owns every rendering. A surface never touches `Store` and never formats a task, so the doors cannot drift.

## Module map

- `orchestrator.py` - the worker process, the serve loop, the CLI.
- `worker.py` - planning, sign-off, execution, gates, retries, model chains, park, jobs.
- `store.py` - the store and the schema.
- `runtime/` - the **fallback** agent loop (model call, tools, MCP pool, skills reader, web search, trimming, logs, todo, park). Selected with `ARIADNE_RUNTIME=own`; the default is Hermes.
- `flows.py` - flow loading, validation, home compilation, `mcp_server_config`.
- `protocol.py` + `render.py` - the plan as data and its one renderer.
- `serving.py` + `resources.py` - where inference is and how much of the machine it may use.
- `models.py` + `modelindex.py` - the catalog and the hardware shortlist.
- `overlay.py` + `bootstrap.py` + `overlay.yaml` - the module overlay over `vendor/hermes`.
- `vendor/hermes/` - the pinned checkout. Never edited.

## The overlay

Import order is repo root, then `vendor/hermes`, then site-packages (`bootstrap.start()`). A module we own lives in `overlay/<package>/<module>.py`; `overlay.apply()` prepends that package's `__path__` with the overlay directory, so our file wins for that module and every other module still comes from the submodule. `overlay.yaml` records module, reason and test; `overlay.check()` fails the suite on a missing one. Updates are a pointer bump plus `uv sync --project vendor/hermes --frozen` - see `tools/sync_hermes.py`.

## MCP hosting

Ariadne exposes four MCP servers to foreign agents: `data`, `office`, `ci`, `rag`. The task MCP (`ariadne_tasks`) is the control surface: submit, wait, approve, revise, cancel, steer. Each step of a running task is reported back to the calling agent - the contract is per-step reporting, not a single final callback.

## State

`.ariadne/` holds everything: `tasks.db` (the store and events), `memory.db`, `logs/`, `homes/<flow>/` (compiled flow homes, sessions, markers), `runtime-sessions/`, `park.json`, `limits.json`, `model-pins.json`, `servers.local.yaml`. It is gitignored; nothing in it is required to read the code.
