# Ariadne is a fork (decision, 2026-11-19)

Ariadne is independent: a **lightweight, local-only fork of Hermes** that provides only what the design promises and
nothing beyond. This supersedes the "overlay on a pinned submodule, never edit `upstream/`" rule in
`docs/DESIGN-RESET.md` — the runtime is ours now. `upstream/` stays as the reference pin we forked from and the
source we cherry-pick fixes from, not as a boundary we may not cross.

## What Ariadne promises (the whole scope)

1. The drill: brief → backbrief → sign-off → execute → gates → report.
2. One task store, one worker, one model on the GPU at a time.
3. Closed sets: approved flows, approved models, approved tools. Unknown is refused.
4. Local-only inference (loopback, LAN, or allowlisted gateway; no keys). Tools may use the internet.
5. Three doors, one stream: our own UI, the terminal, and MCP. Sessions are the unit of work; schedules are created
   from a session.
6. Durable memory and skills that change the *next plan*, not just the next run.

Anything not on that list is out of scope. If a feature cannot be tied to one of the six, it does not get built.

## What we keep from Hermes

- the agent loop and tool calling
- sessions, resume, and context compaction
- the tool implementations the flows approve: terminal, files, search, web fetch/search, browser, VS Code, jobs
- the MCP client (and our own MCP servers)
- skill loading
- model clients for OpenAI-compatible and Ollama endpoints
- the hook points (`pre_tool_call`) that let a flow restrict a phase to read-only tools

## What we strip

- the Electron desktop app and its shell: routes, capabilities, connectors, bots/agents, artifacts, cron UI,
  starmap, pet overlay, command center
- messaging platforms (Telegram, Slack, Discord) and account sign-in
- hosted connectors and anything that brokers a third-party credential
- cloud providers, the model catalog / models.dev fetch, telemetry, update checks
- computer-use and media generation, except where an approved flow names them (the content flow needs image gen)
- multi-profile management

Dependency footprint after the strip: Python, Ollama, git, uv. **Node is no longer required** — it was only there
for the desktop build.

## How the fork is maintained

- The fork lives in our tree (working name `ariadne/runtime/`), created from the recorded pin
  `458a0046ad6ce75f6f7b2705f592b9c7a749fe14`. `upstream/` remains checked out at that pin for diffing.
- Stripping is **deletion with tests**, never rewriting: remove a subsystem, run the suite, commit. Each removal is
  recorded below with its reason so the diff stays reproducible.
- Upstream fixes are cherry-picked deliberately; the pin is bumped only when a fix matters to us.
- Nothing in the fork may reach a cloud provider: `ariadne/local_only.py` is checked before any run, and the fork
  has no provider code left to bypass it.

## What this changes now

- `install --system` drops Node.
- `ariadne up` starts the models and our server — no gateway, no desktop.
- The worker calls our runtime directly, which makes "one session per task" (the reset's step 5) a small change
  instead of a fight with a subprocess CLI.
- The gate plugin retires: our chat is ours, so it is simply not given doing-tools.

## Strip log

| Removed | Reason |
|---|---|
| `desktop/`, `ariadne/desktop.py`, branding overlay | frontend pivot — our own UI (`docs/FRONTEND.md`) |
| `plugins/offline_guard` | blocked all egress; contradicts "the model may use the internet" |
| `flows/_retired/writing` | flow retired; content covers written work |
| `agent.disabled_toolsets` | inert — never changed the tool list |

Next: the runtime strip itself, in the order above, one subsystem per commit.
