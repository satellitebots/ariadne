# Ariadne is a stripped fork of Hermes

Ariadne is a **fork of Hermes**: the pinned tree is copied into this repo and gutted down to one scenario - a
local-only task harness with a brief, a backbrief, a sign-off, an execution and gates. What remains is Hermes's agent
core (loop, tools, skills, MCP client, compression, provider handling) as Ariadne's own code, plus the orchestrator
Ariadne adds. There is no upstream to track and no compatibility promise: we forked once, we own the result.

| Ariadne owns (the orchestrator) | Hermes owns (the worker backend) |
|---|---|
| the drill: brief -> backbrief -> sign-off -> execute -> gates -> report | the agent loop and tool calling |
| the task store, the service layer, the presentation | the tool implementations (file, terminal, search, todo, ...) |
| the HTTP server and the SPA (replaces Hermes's desktop app) | skills loading and progressive disclosure |
| the chat surface (replaces Hermes's chat) | the MCP client and its server lifecycle |
| our MCP servers and the MCP hosting surface | context compression and session handling |
| the model catalog, the model index, the local-only lock | provider handling: streaming, reasoning effort, fallbacks |
| schedules, park, the watchdog | |

**Replace only what has the wrong hook.** The desktop app, the chat and the MCP hosting surface are Ariadne's because
their integration points belong to the orchestrator (a task console, a conversation bound to a session, a tool surface
for callers). Everything else is Hermes's and is used as it ships.

## How the fork is built

`vendor/hermes` is a **pristine git submodule** at the pin. We never edit inside it, so a pin bump is a pointer change
and never a merge. Our code is an overlay on top:

- **Resolution order**: repo root, then `vendor/hermes`, then site-packages. `ariadne/overlay.py::install()` sets it,
  and every entry point that can import Hermes calls `bootstrap.start()` first.
- **Modules we own** live in `overlay/<package>/<module>.py`. `overlay.apply()` prepends that package's `__path__`
  with the overlay directory, so our file wins for that module while every other module still comes from the
  submodule. No copying, no patching, no edited upstream files.
- **The ledger** is `overlay.yaml`: each entry names the module, why we own it, and the test that proves it.
  `overlay.check()` fails the suite if a declared module has no file, no reason or no test - so an upstream rename is a
  visible failure, not a silently dead shadow. Empty is the normal state: the runtime gut is configuration, not code.
- **Updates**: `python tools/sync_hermes.py --to <tag|commit>` fetches, checks out, stages the pointer and rebuilds the
  venv from the submodule's own lockfile (`uv sync --project vendor/hermes --frozen`). Then `pytest -q`. The contract
  tests (`test_hermes_contract.py`) name any CLI flag, config key or hook that moved, and `worker.hermes_run` is the
  only adapter that should need a fix.
- **The runtime gut**: `enabled_toolsets` per phase, `disabled_toolsets` for the rest, and a flow-home config with
  telemetry, updates and catalog fetch off and only our plugin enabled. The gateway, desktop, bots and messaging code
  is present but never launched and never on the task path. `local_only` still refuses any non-loopback/LAN endpoint.

## The own runtime is a fallback, not the product

`ariadne/runtime/` (loop, eight tools, MCP client, skills reader, web search, trimming, logs, todo, park) stays in the
tree, selected with `ARIADNE_RUNTIME=own`. It exists so a worker can run when the Hermes install is unavailable, and
because it lets the whole task path be proven model-free in tests. It is not where the workers' capabilities are grown:
that is Hermes's job.

## What over-reached, and what stands

B12.7 deleted Hermes and made the own runtime the default. That contradicted the intent and broke the venv's `hermes`
install (it had been an editable install pointing at the deleted tree). B17 restored the submodule at `vendor/hermes`,
rebuilt the venv from its lock, and put `hermes_run` back as the default.

What stands from B12: the fallback runtime and its MCP client, skills reader and web search; context trimming and
per-run logs; `todo_write`; the park boundary and the MCP markers; and the chat, which runs on the own runtime with
`native_tools=False` so it can submit tasks and search but cannot touch a file.

## Forced differences (constraints, not preferences)

- **Local inference only.** Every model runs on this machine, or on a localhost/LAN Ollama server registered in
  `serving/servers.yaml`. A cloud provider is refused by `local_only` at every command that can start a model. That is
  why the catalog, the model index and the serving registry are Ariadne's: Hermes assumes a hosted provider by default.
- **No messaging.** Telegram, Slack, Discord and the bot gateway are not surfaces Ariadne has. There is nothing to
  connect and nothing to configure; the doors are the SPA, the terminal, the chat and MCP.
- **Flows replace bots.** A Hermes bot is a persona with a soul file. Ariadne's unit is a **flow**: a folder with
  `flow.yaml`, `FLOW.md`, skills and gates that declares the model, the toolsets, the MCP servers, the plan-phase
  allowlist and how done is checked. A person signs off a plan, not a personality. That is the better system for this
  work, and it is why the bot/soul surface was not carried over.
- **Because those interfaces differ, the surfaces were replaced** - desktop app, chat, messaging, bots - while the
  worker backend stays Hermes's.

## Scope that does not come back

The Electron desktop shell, messaging platforms, hosted connectors and sign-in, cloud providers, the model catalog
fetch, telemetry and update checks, computer-use, and multi-profile management are out of scope for Ariadne's product.
They are not stripped from the pinned checkout; they are never launched, and the flow homes disable them. Node is
required only for the diagram (`npx mmdc`) and browser (`npx chrome-devtools-mcp`) MCP servers.
