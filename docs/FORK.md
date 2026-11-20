# Ariadne is independent (decision, 2026-11-19; completed 2026-11-19)

Ariadne is not a fork any more: it is its own **lightweight, local-only task harness**, and it owns every part of it.
The pinned Hermes submodule was deleted at B12.7 - the agent loop, the tool registry, the session store, the chat and
the model plumbing are all `ariadne/` code now. There is no upstream pin to track, no `upstream/` directory, and no
`hermes` binary in any path.

This supersedes the earlier "overlay on a pinned submodule, never edit `upstream/`" rule and the fork-and-strip plan.
That plan was measured first: `agent/` alone was 468 modules and 162,839 lines, so "delete one subsystem per commit"
had no bottom. The replacement is `ariadne/runtime/` - one OpenAI-compatible call, eight native tools, a resumable
message list, a 96-line loop - plus the MCP client, the skills reader and the web search that sit beside it.

## What Ariadne promises (the whole scope)

1. The drill: brief -> backbrief -> sign-off -> execute -> gates -> report.
2. One task store, one worker, one model on the GPU at a time.
3. Closed sets: approved flows, approved models, approved tools. Unknown is refused.
4. Local-only inference (loopback, LAN, or allowlisted gateway; no keys). Tools may use the internet.
5. Three doors, one stream: our own UI, the terminal, and MCP. Sessions are the unit of work; schedules are created
   from a session.
6. Durable memory and skills that change the *next plan*, not just the next run.

Anything not on that list is out of scope. If a feature cannot be tied to one of the six, it does not get built.

## What is ours (and where)

- **The loop**: `ariadne/runtime/loop.py` - prompt, tool calls, tool results, turn and time budgets, context
  trimming, park boundaries. `model.py` speaks one OpenAI-compatible `/chat/completions`.
- **The tools**: `runtime/tools.py` - read, write, patch, search, list, terminal, todo_write - with a workspace jail
  and the read-only phase enforced at dispatch, not in a prompt.
- **The MCP client**: `runtime/mcp.py` - the flow's servers over stdio, namespaced `mcp__<server>__<tool>`, filtered
  for read-only phases by the flow's own `plan_tools`.
- **Skills and search**: `runtime/skills.py` (`skills_list`, `skill_view`) and `runtime/web.py` (`web_search`).
- **The worker**: `worker.py` - plan, sign-off, gates, retries, model chains, park, jobs, wall clock. Its runner is
  `runtime_run`; the Hermes CLI adapter is gone.
- **The chat**: `chat.py` - the same runtime with `native_tools=False`, so it can submit tasks and search and cannot
  touch a file. No gate hook: the tools simply do not exist in that conversation.
- **The rest**: the store (`store.py`), the service layer (`service.py`), the presentation (`present.py`), the HTTP
  server and SPA (`server/`, `ui/`), the model index (`modelindex.py`), and our MCP servers (`*_mcp.py`).

## What we removed, and why it stays removed

- the Electron desktop app and its shell (routes, capabilities, connectors, bots, artifacts, cron UI, starmap)
- messaging platforms and account sign-in
- hosted connectors and anything that brokers a third-party credential
- cloud providers, the model catalog fetch, telemetry, update checks
- computer-use, except where an approved flow names a tool
- multi-profile management
- **the submodule itself**: keeping 163k lines checked out to diff against is a cost with no owner. What we needed
  from it - the shape of a tool-calling loop, a message list, a tool registry - is now written down and tested here.

## Dependency footprint

Python (with `mcp`, `fastapi`, `uvicorn`, `ddgs`, `ruamel.yaml`), `uv`, `git`, and optionally Ollama. **Node is
required only for two MCP servers** - the diagram renderer (`npx mmdc`) and the browser (`npx chrome-devtools-mcp`).
Nothing in Ariadne's own process is Node.

## How it is maintained now

- The product is this tree. There is no upstream to rebase onto and no pin to bump.
- Changes follow the same rule as before: tests first where behaviour is involved, `docs/` updated in the same
  commit, and an item is done only when a test exercises it with `HERMES_EXE` pointed at a path that does not exist.
- The two items that outlived the flip are B15 (the wiki rewrite) and the deferred GPU work in `docs/BACKLOG.md`.
