# Ariadne

Ariadne is a **local-only task harness**: you give it a brief, it returns a plan you sign off, it executes on your own
machine, and check gates decide whether it is done. It is an **orchestrator** - the agent that does the work is
Hermes, pinned as a submodule (`vendor/hermes`) and overlaid, never edited.

Ariadne is a *fork-ish* of [Hermes Agent](https://github.com/NousResearch/hermes-agent): we keep its agent loop, tools,
skills, MCP client, context handling and provider plumbing as the worker backend, and we replace only the surfaces
whose integration point belongs to the orchestrator - the console, the chat, and the MCP hosting surface. The
runtime gut is configuration, not code: messaging, bots, connectors, cloud providers, telemetry and the desktop shell
are present in the tree but never started.

## The six promises

1. The drill: brief -> backbrief -> sign-off -> execute -> gates -> report.
2. One task store, one worker, one model on the GPU at a time.
3. Closed sets: approved flows, approved models, approved tools. Unknown is refused.
4. Local-only inference (loopback, LAN, or an allowlisted gateway; no keys). Tools may use the internet.
5. Three doors, one stream: our console, the terminal, and MCP. Sessions are the unit of work; schedules are created
   from a session.
6. Durable memory and skills that change the *next plan*, not just the next run.

## Quick start

```sh
python -m ariadne install --system      # system tools, once
python -m ariadne doctor                # what is missing (changes nothing)
python -m ariadne models index          # what this machine can run, by tier
python -m ariadne up                    # model server + MCP endpoint
python -m ariadne ui                    # the console at http://127.0.0.1:8917
python -m ariadne "fix the failing date test"   # one gesture
```

## The documents outrank this wiki

| Document | What it decides |
|---|---|
| [`docs/FORK.md`](../docs/FORK.md) | the fork, the overlay, what is replaced and why |
| [`docs/DESIGN-RESET.md`](../docs/DESIGN-RESET.md) | the drill and the backend shape |
| [`docs/FRONTEND.md`](../docs/FRONTEND.md) | our console and chat |
| [`docs/MODELS.md`](../docs/MODELS.md) | model servers, catalog, the index |
| [`docs/MCP.md`](../docs/MCP.md) | MCP client integration |
| [`docs/COVERAGE.md`](../docs/COVERAGE.md) | per-flow tool coverage and the runtime contract |
| [`docs/BACKLOG.md`](../docs/BACKLOG.md) | the queue and what is deferred |

## Pages

| Page | What it covers |
|---|---|
| [Architecture](Architecture.md) | the components, the module map, the overlay |
| [Concepts](Concepts.md) | task, session, flow, gate, park, job, skill |
| [Task Lifecycle](Task-Lifecycle.md) | brief to report, step by step |
| [Flows and Skills](Flows-and-Skills.md) | what a flow is, how skills steer it |
| [Models and Resources](Models-and-Resources.md) | catalog, profiles, the model index |
| [Jobs](Jobs.md) | handing heavy work to Ariadne |
| [Parking and KV Cache](Parking-and-KV-Cache.md) | pausing and resuming cheaply |
| [Web and Browser](Web-and-Browser.md) | search, fetch, the debug browser |
| [CLI Reference](CLI-Reference.md) | every command |
| [Operations](Operations.md) | running it, troubleshooting |
| [Decisions](Decisions.md) | the choices and their reasons |
| [Status and Roadmap](Status-and-Roadmap.md) | what is proven, what is deferred |
| [Case Studies](Case-Studies.md) | real tasks |
