# Ariadne is the orchestrator; Hermes is the worker backend (corrected 2026-11-19)

Ariadne is an **orchestrator**: it decides what work happens, who signs it off, how it is checked, and how it is
reported. The agent that does the work is Hermes, and it stays Hermes. Reworking its loop, tools, skills, MCP client,
context handling or provider plumbing was never the goal - those are the backend, and they are the part that would
take a rewrite to reproduce.

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

## How Hermes is pinned

- `vendor/hermes` is a git submodule at `458a0046ad6ce75f6f7b2705f592b9c7a749fe14`.
- Ariadne's venv is built from **Hermes's own lockfile**: `uv sync --project vendor/hermes --frozen --python 3.14
  --extra mcp --extra ddgs`. That is what puts `hermes.exe` in `.venv/Scripts` and makes the toolset surface real.
- `worker.hermes_run` spawns that `hermes` with the flow's compiled home, toolsets, skills and model: prompt in,
  report out, session id to resume. It is the **default runner**.
- **Do not install `hermes-agent` from git as a plain package.** At this pin it does not resolve outside its lockfile
  (`browser-harness` needs `pillow==12.3.0` while Hermes pins `pillow==13.0.0`), and the machine's own Hermes is a
  frozen binary, not an importable environment. The pinned checkout plus `uv sync --frozen` is the supported form.

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
