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

**One backend.** Every front is a funnel onto the same verbs: the UI's HTTP routes, the terminal (`ariadne <verb>`
and the chat's slash commands), the orchestrator's tools and MCP all end in `verbs.call`, and nothing a front does
is behaviour of its own. Even "wake the worker after a verb that may queue work" is one rule in the registry
(`verbs.WAKES`), installed by each front that serves a person; before 26 Nov each front kept its own list and a run
the orchestrator signed from the terminal chat sat queued. The mock backend seeds through the same verbs.

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
outputs (files it must leave), gate (command or review), and optionally `each: <plan file>`.

**Steps are the backbone.** A task is a sequence of small steps, each a fresh session with its own outputs and check;
nothing else gives a local model a chance at a long piece of work. Every template starts the same way: a planning
step writes a plan file with a `## Steps` list (gated by `checks/plan_steps.py`), then an `each:` step runs once per
item of that list ({item}, {i}, {count} filled in), then a deterministic check. The engine expands an `each:` step
when it reaches it and stores the run's own plan, so the run page, a resumed run and later steps see the concrete
steps ("Write 3/7: Divide and conquer"). A template-less flow gets the same shape (plan, each, check), never one big
"do the task" step: that put a whole study guide in one 8-minute model call (case study, 26 Nov).

**Gates: facts first, judgment once.** Command gates (scripts in `checks/`) retry a step once with their findings.
A review gate is a model's judgment, and a weak local reviewer can be wrong in both directions, so a failing review
is never retried: the run goes to `needs_you` with the reviewer's words, and the person decides. Templates carry at
most one review, at the end, and only where claims need sources. `retries` is 0 to 4.

**Structure guides, it never fences.** Ariadne is for empowerment: the freest worker a local model can be. Every
step and every reviewer has all of its flow's tools (toolsets and MCP servers; a definition may narrow a step on
purpose, nothing narrows it by default). Plans have no size limits; a size or a long line is a note, not a failure.
Instructions say what to focus on, never what is forbidden ("fix anything this step depends on, and say so").
`piece_check.py` is a tool the worker runs to find gaps; it blocks only with `--strict`. The only gates in the
templates are facts: a plan has a `## Steps` list, the worker's own CHECK.md says PASS.

**Trigger**: `manual`, `now`, `at <time>`, or `cron <expr>` with a time zone. `now` runs once, started by signing;
the scheduler never starts `now` or `manual` (on 26 Nov it re-ran a `now` task after every run). Missed runs while
the machine was off run once on wake, not once per miss.

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

No clocks, no caps: a step, a review, a job and an orchestrator turn run until they finish. Stopping is always
deliberate (cancel, park). A cancel stops the worker at once, even mid model call; a park and an ask wait for the
call in flight to finish, because they resume the same session. Instead of a budget, progress is pushed as it happens: every tool call (from the phase
plugin's log), every finished model call (Hermes's agent.log) and a running job's newest output become run events
("step 2: wrote data/indicators.json", "step 2: ran: ...", "model call 4: 17,227 tokens in"). A long quiet spell
adds one "quiet" event, never a kill. The `progress` verb (every front) answers "is it still moving?": seconds since
the last activity, tool and model call counts, the files changed, the recent activity. An outside orchestrator over
MCP reads it before deciding anything; the terminal chat's /status and the UI's "Now:" line show the same.

Workers have no Hermes restrictions. Hermes caps its agents because it expects hosted models; Ariadne's are local, so
its approval layer, dangerous-command and hardline blocks, read-before-write, sensitive-path, protected-file and
binary-file guards, read blocks on credential paths, URL/SSRF and cloud-metadata blocks, secret-shaped-URL refusals,
workdir validation, repeated-read blocks, loop hard stops and private-URL block are all off, and the step prompt
tells the model that everything is permitted and never to report something as not allowed. Hermes's limits for
fast hosted models are lifted too: turn liveness (600 s of silence aborted a turn; one local call took 482 s),
the gateway, stall and stale-stream clocks, the compressor's timeouts, page, file and command-output truncation
(15,000 characters, 100,000, 50 KB), and small caps on delegation, goals, loops, memory and skill shells
(`flows.BASE_CONFIG`; a test pins them, and the compiled home is checked with Hermes's own loader) (`flows.BASE_CONFIG`, `permissions.HERMES_ENV`, and the
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

`flows/<name>/template.yaml`: parameters (with the questions the orchestrator or the draft form asks), steps
(title, instruction with `{params}`, tools, outputs, gate, `each:`), task gates, and the default trigger. Each flow
lists only the tools its steps need; a test validates every template as a task. Templates:

| Flow | Steps |
|---|---|
| investigation | bound the question → gather sources (ledger) → compute the facts (script) → write → verify; one review |
| coding | plan the change (`## Steps`, `## Done when`) → one step per change → prove it (`CHECK.md`, `RESULT: PASS`) |
| content | outline from the sources (ledger, conventions) → one step per section → assemble and check (`piece_check`); one review |
| design | scope the views → one step per view (Mermaid + section) → assemble and check |

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
