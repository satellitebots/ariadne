# Design: one front, an orchestrator that defines, workers that do, one owner of the machine

Authority #2 (see `CONVENTIONS.md`). Supersedes `GAP-ANALYSIS.md`. Written 2026-11-24 after the first round of real
runs failed (see the inventory in the session notes): no real task finished end to end after 18 Nov, zero jobs
were ever submitted, and every failure traced back to the orchestrator, the worker, jobs and the embedder fighting
over one 8 GB GPU and 32 GB of RAM.

## The goal

A person, with the help of the orchestrator, either defines a **durable task** (a chain of steps) and runs it, or
schedules it to run at a given time and frequency. Everything below serves that sentence.

## Five parts

| Part | Is | Is not |
|---|---|---|
| **Front** | MCP, the UI and chat: three adapters over one set of verbs (`service.py`) | A place with features of its own |
| **Orchestrator** | A local model that talks with the person and produces a task definition | A worker: it never edits files, runs commands or submits jobs |
| **Task / Run** | A task is a signed, versioned definition. A run is one execution of a version | The same row (today a task is both) |
| **Worker** | A headless Hermes run for one step: instruction, inputs, tools, gate | A chatbot, a gateway, a persona |
| **Broker** | The only owner of the model server: one lease, one holder, a visible queue | Optional: nothing else loads or unloads a model |

Flows sit across them: a flow is a **template for durable tasks** (the structured bot). It fixes the step skeleton,
the tools each step may use, the default gates and the models. The orchestrator fills a flow in; it does not invent
plans from nothing.

## Fronts: one contract

Every verb exists on all three fronts with the same name, arguments and answer, or it does not exist. A contract
test walks the verb list against the MCP tool list, the HTTP routes and the chat's tools.

| Group | Verbs |
|---|---|
| Define | `draft(text, flow?)`, `say(draft, message)` (one orchestrator turn), `draft_show`, `sign(draft)`, `edit(task)` (a new draft from a signed version) |
| Tasks | `tasks`, `task`, `schedule(task, trigger)`, `unschedule`, `retire` |
| Runs | `run(task)` (now), `runs`, `run_show`, `park(run)`, `steer(run, text)`, `resume(run)`, `cancel(run)`, `rerun(run)` |
| Machine | `machine` (who holds it, who waits, the next boundary) |

**Chat** is the orchestrator conversation itself; its tools are the verbs above, nothing else.

**The UI** renders the same verbs and adds nothing.

**MCP is the bypass.** An outside agent (e.g. Claude) may skip the local orchestrator: `define(spec)` takes a full
task definition and returns it as a draft to sign, so the local orchestrator model never loads. MCP also exposes the
extra control a capable agent needs: `machine_release`, `run_logs`, `job_output`, `events` (raw).

## The orchestrator

- **Local, always.** It shares the GPU with the workers, so it holds the lease while it talks.
- **Defines, never works.** Tools: read-only workspace, `web_search` / `web_fetch`, memory recall, and the Define
  verbs. Its only output is a draft task.
- **Prefers the worker's model.** When the flow's worker model can also orchestrate, the orchestrator runs on the
  same weights, so a handoff is a KV-cache switch, not an unload and load.
- **Sleeps when the person signs.** The draft is saved; the orchestrator's cache is parked; the lease goes back.

## Durable tasks and runs

**Task** (stored as `.ariadne/tasks/<id>/v<N>.yaml` plus a row): name, flow, workspace, goal, parameters (what the
flow template asked for, e.g. a ticker), steps, task gates, trigger, budget, failure policy, version, status
(`draft` | `signed` | `retired`).

**Step**: number, title, instruction, model, tools (a subset of the flow's), inputs (files from earlier steps),
outputs (files it must leave), gate (command or review).

**Trigger**: `now`, `at <time>`, or `cron <expr>` with a time zone. Missed runs while the machine was off run once
on wake, not once per miss.

**Run**: run id, task id + version, trigger, status (`queued` | `waiting` (for the machine) | `running` | `parked` |
`done` | `failed` | `timed_out` | `cancelled` | `needs_you`), current step, per-step results, log.

**Failure policy** (default): retry the failed step once with the gate's reasons; then `needs_you`, and the schedule
keeps going. A signed version is immutable: editing makes a new version to sign, and runs in flight finish on the
version they started.

## Workers

One headless Hermes run per step, fresh context, handing over through the step's output files. The prompt carries
the step's instruction, inputs, gate, and any steering notes. Heavy work leaves as jobs (`submit_job`); the flow's
tool list keeps the terminal for quick commands only. Hermes's gateway, messaging, persona and chat memory are not
used.

Workers have no Hermes restrictions. Hermes caps its agents because it expects hosted models; Ariadne's are local, so
its approval layer, dangerous-command and hardline blocks, read-before-write, sensitive-path and protected-file
guards, loop hard stops and private-URL block are all off (`flows.BASE_CONFIG`, `permissions.HERMES_ENV`, and the
interpreter overlay `tools/permissions_hook.py`; vendor stays untouched). The only rules are the person's own,
in `permissions.yaml`: default allow; `ask` lists tools, command regexes or write paths that hold a run (status
`asking`, machine released) until `approve` or `reject`; `deny` refuses outright.

## The broker: one owner of the machine

- **One lease.** Holders: the orchestrator (a draft), a worker (a run's step), a job. The rest wait in the queue,
  which every front shows.
- **Handoff only at boundaries.** A step boundary or a finished tool call, never mid-generation. Sequence: the holder
  stops at the boundary → its KV cache is saved → the broker unloads (or only switches the slot, same weights) → it
  checks memory is actually free → the next holder loads → its cache is restored if resuming.
- **Priority.** A running step keeps the machine until its boundary. A person who opens the orchestrator waits for
  that boundary, with an estimate. To take the machine now, the person **parks** the run on purpose; nothing is
  interrupted on its own.
- **Steering is park, then steer.** In any front: park the run → talk to the orchestrator about it (it has the run's
  state) → `steer` records the note → `resume` hands the machine back and the next step starts with the note.
- **Jobs unload everything** and get the whole machine, then hand back.
- **The scheduler asks too.** A trigger creates a queued run; it waits for the lease like anyone else.
- **The broker starts the model server.** No component assumes a server is up (the 19 Nov plan failures).

## Flows as templates

`flows/<name>/flow.yaml` gains a `template` block: parameters (with descriptions the orchestrator asks about), steps
(title, instruction with `{params}`, tools, outputs, gate), task gates, and the default trigger. Each flow lists only
the tools its steps need; nothing is on by default. First flow to rebuild: **investigation** (gather data as a job →
analyse → write with citations → verify).

## Cut list

| Goes | Why |
|---|---|
| Sessions as hosts (`sessions` table, `define_session`, busy gate refusals) | Tasks and runs carry what sessions tried to; the queue replaces refusals |
| A task that is also its execution (statuses `awaiting_gates`, `awaiting_signoff`, ...) | Task / Run split |
| Schedules of a session's brief | Schedules point at a signed task version |
| `ARIADNE_RUNTIME=own` as a worker runner | One worker engine (Hermes); the own runtime stays only for the orchestrator conversation |
| `.hermes-home` terminal entry point and the `ariadne-tasks` Hermes skill | Chat is ours |
| Hermes gateway use (`stop_gateway`) | Headless runs only |
| Every MCP server on for every flow | Per-step tool lists |

Kept: gates and the QA loop (per step and per task), jobs, KV parking, the watchdog (as the broker's memory check),
`local_only`, the model catalog and index, `present.STATUS` (rewritten for runs), the flows, skills and case studies.

## Order of work

1. **Broker:** lease, queue, handoff, `machine` verb, the server started by the broker. Tests with a fake server.
2. **Task / Run split:** schema, YAML versions, verbs, migration (old tasks become read-only legacy runs).
3. **Flows as templates:** investigation first.
4. **One contract:** verbs on MCP, HTTP and chat, and the contract test.
5. **UI revamp** on the new verbs: tasks and schedules, a task's definition and its runs, the orchestrator
   conversation beside them, the machine status always visible.
6. **Proof:** the GOOGL investigation defined in chat, signed, run on real models with a job, then scheduled.
