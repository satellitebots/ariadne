# Design reset
> **Partially superseded (2026-11-20).** 'Must not own an agent loop' and 'never edit upstream' are overridden:
> Ariadne owns a small runtime runner as fallback, Hermes is the worker backend via the `vendor/hermes` submodule
> plus overlay (BACKLOG B12/B17/B18, see also B18), and Ariadne owns its UI and chat. docs/CONVENTIONS.md lists
> the authority order.



This is the authority on what Ariadne is and how it should be built. The code before this document is a series of
patches that answered yesterday's complaint; where the code and this document disagree, this document wins and the
code is legacy to be migrated, not a baseline to extend.

## What Ariadne is for

One person, one GPU, no cloud. The person has work they cannot trust an agent to do unattended: change code, produce
a design, investigate a question, write and illustrate content. Ariadne's product is not "an agent that does it". It
is **a decision surface around autonomous work**:

1. **Define** - turn an intent into something a reviewer can judge: a brief, a workspace, and check gates ("how do we
   know it is done").
2. **Decide** - produce a *backbrief* (mission, steps, the model per step, which step satisfies which gate) and stop.
   The person approves, revises, or cancels. Nothing runs before that.
3. **Execute** - a worker runs until the plan's own checks pass, retrying with the failure reasons.
4. **Report** - what changed and how it was verified, in the workspace and in the task record.

Everything else - flows, model policy, MCP servers, the desktop page - exists to make those four jobs trustworthy on
a local machine. If a feature does not serve one of them, it is scope.

## What Hermes already is (and therefore what Ariadne must not rebuild)

Hermes is an agent runtime: model/provider configuration, the tool-calling loop, sessions and resume, MCP client,
skills, approval hooks, a plugin API, and a desktop shell with declared contribution areas (routes, sidebar, status
bar, composer). Ariadne is an overlay on a pinned Hermes; the whole point of the overlay is to *use* those.

So Ariadne must not own: an agent loop, a tool registry, a session store, a chat UI, or a model server. We own a task
store, the decision protocol, flow data, model policy, and the gate runner. Anything else is re-implementation.

**Amendment (2026-11-19, the person's instruction).** The alternative to owning the loop turned out to be owning a
fork of the pin - `agent/` alone is 468 modules and 162,839 lines, and "delete one subsystem per commit" has no
bottom. So the loop, the tool registry and the session list are now Ariadne's own, in `ariadne/runtime/`: one
OpenAI-compatible call, eight tools with a workspace jail, a resumable message list, and a 96-line loop. That is
smaller than the glue the fork needed, it is model-free testable, and it is the reason a task can run with `hermes`
absent (`tests/test_runtime_drill.py`). B12.7 then went too far and made it the default; B17 corrected that: Hermes is
the worker backend again, pinned at `vendor/hermes` with the venv built from its lockfile, and `ariadne/runtime/` is
the opt-in fallback (`ARIADNE_RUNTIME=own`). Ariadne orchestrates; Hermes does the agent work. The rest of this
document stands.

## What we built, honestly

- `orchestrator.py` (~1,300 lines): store, router, prompt assembly, plan parsing, execution loop, gate runner, retry
  policy, VRAM control, worker supervision, CLI rendering helpers.
- Three surfaces with their own rules: `console.py` (CLI), `tasks_mcp.py` (MCP), `desktop/plugin/...` (HTTP +
  JSX). Each validates flows, models, statuses and messages independently.
- A plan that is prose. `parse_model_plan()` regexes it in Python, `briefParts()` regexes it again in JavaScript, and
  `model_block()` appends more prose to it.
- A chat home that was a first-class door, then had its tools removed, then a `pre_tool_call` gate installed to
  refuse the tools that remained.

## Where it went wrong

**1. A second agent runtime.** `Worker.run()` spawns `hermes chat -z` once per step and reimplements iteration,
context carry-over, timeouts and retries around it. Hermes already is that loop. Consequence: the model reloads per
step, each step restarts from a fresh context, the retry policy fights the agent's own, and ~400 lines exist only to
supervise subprocesses. The per-step model feature is what forced this; it should be a deliberate *chain of
sessions*, declared in the plan, not a hidden spawn per step.

**2. Three rulebooks for one task.** The explicit-flow-and-model rule had to be written twice (HTTP and CLI), the
stale-`executing` rule three times, and the approved-flow check in two places with different messages. Every rule is
a place for the surfaces to disagree. The desktop is where the disagreement becomes visible.

**3. Prose as the protocol.** One backbrief, three parsers. `model_block` appends `task model:` and per-step lines;
`parse_model_plan` reads them back with a regex; `briefParts` splits the same text again for the page. A plan is
data. Formatting belongs in exactly one function.

**4. The chat contradiction.** We wanted the chat to be a full door, discovered a capable model just does the work,
and answered with tool removal plus a gate. That is treating a symptom: a chat whose only verb is "submit" is a form
with latency. Its honest job is to help compose the brief and hand it over - and it should have no doing tools *by
construction*, not by a hook that says no after the model has decided.

**5. UI before protocol.** We built a task board, then a ritual, then patched the ritual twice. Each rebuild cost
more than freezing four verbs and one document would have. The screen is a view; the protocol is the product.

## What is right and stays

- **Closed sets.** Flows (`flows/flows.yaml`), models (`policy.families`), tools (`flows/tools.yaml`). Unknown is
  rejected, never guessed. A cheap planner cannot invent coordination; `FLOW.md` supplies it.
- **The ritual.** Brief → backbrief → sign-off → execute → QA → report. The person decides on a document, not a
  queue.
- **Explicit choice.** The person names the flow and the model; no silent routing, no auto-selection in the UI.
- **The store as the single source of truth** across terminal, desktop, MCP and chat.
- **Approval authorises downloads**, and the backbrief names them before sign-off.
- **Model policy for the card**: approved families, ~11B preference, the orchestrator unloads after sign-off.
- **Desktop as a Hermes plugin** through declared contribution areas - the only supported way in.

## The shape from here

```
ariadne/
  store.py      tasks, events, sessions (sqlite)                 # built (B5)
  flows.py      flow data + closed sets                          # keep
  models.py     catalog, policy, install                         # keep
  protocol.py   the task document + the verbs, no I/O            # NEW - frozen centre
  service.py    submit/approve/revise/gates/cancel/status        # NEW - the only rulebook
  worker.py     one Hermes session per task, gates at the edge   # built (B4)
  render.py     plan JSON -> the backbrief document               # NEW - the only formatter
  surfaces/     cli, mcp, desktop api                            # adapters, no rules
```

`orchestrator.py` is now the worker process and the `task` CLI; `console.py` is the terminal adapter. The store is
reached only from `service.py` (and by `worker.py`, which records progress while a task runs).

**The task document** (what every surface reads and writes):

```json
{
  "id": "t1120-101500-ab12", "status": "awaiting_signoff",
  "brief": "fix the failing leap-year test", "flow": "coding", "model": "qwen3.6-35b-a3b",
  "workspace": "C:/repos/proj", "session": "proj",
  "plan": {
    "mission": "the leap-year test passes",
    "steps": [{"n": 1, "text": "fix parse_date()", "model": "qwen3.6-35b-a3b"}],
    "gates": [{"id": "G1", "text": "pytest -q", "run": true, "step": 1}],
    "risks": ["..."], "questions": ["..."]
  },
  "feedback": "", "result": "", "error": "", "events": []
}
```

**The verbs** (the only mutations): `submit`, `approve(models)`, `revise(feedback)`, `set_gates`, `cancel`,
`status/list`. Every surface calls `service.py`; no surface owns a rule.

**The worker** is one Hermes session with the approved model, approved toolsets, and the rendered plan as its brief.
It works until it reports done; Ariadne then runs the gates. A failed gate resumes *the same session* with the
failure (`hermes chat -r`). Steps are guidance inside one context, not processes. When a step genuinely needs a
different model, the service splits the task into an explicit chain of sessions, records it in the plan, and each
session gets a carry-forward note. No hidden spawning, no per-step reloads.

## Migration (each step shippable on its own)

1. **Data first.** `protocol.py` + `render.py`; the planner returns a fenced JSON plan; the store keeps `plan_json`
   and renders the document from it. Fallback to prose for one release, then delete the regex parser. *(slice 1,
   below)*
2. **One rulebook.** `service.py`; CLI, MCP and desktop become adapters. Delete the duplicate validation and diff the
   messages; they must be identical because they are the same function.
3. **One session.** ~~`worker.py` replaces the per-step loop; gate failures resume the session; delete
   `step_groups`, `agent_for`, the per-step retry machinery, and the subprocess supervisor.~~ **Done (B4)**:
   `ariadne/worker.py` owns execution; the plan records `models.chain` (a session per agent model, with a
   carry-forward note); a failed gate resumes the same Hermes session with only the failure; `step_groups` and
   `agent_for` are gone.
4. **The chat, honestly.** Launch the chat home with a minimal toolset (`-t mcp-ariadne_tasks,skills,clarify`), keep
   the gate only as a backstop, and retire `agent.disabled_toolsets` (it did not change the tool list, so it is a
   false assurance). The chat composes and submits; it does not work.

## Delete list (do not port these forward)

- `parse_model_plan`, `model_block` as a second formatter, `briefParts` as a third parser.
- per-step `hermes chat -z` spawning and the retry loop around it.
- duplicate flow/model/status validation in `plugin_api.py`, `tasks_mcp.py`, `console.py`.
- `agent.disabled_toolsets` as an enforcement claim.
- the task board vocabulary (tickets, queue) if any remains in copy.

## Local-only, precisely

The lock is on **inference**, not on the network. A local model may search, fetch and download; what it may not do is
call someone else's model or hold a key. Enforced by `ariadne/local_only.py` at every command that can start a model
(`up`, `serve`, `chat`, `task`, `desktop`) and before `profile` writes a home:

- every `base_url` under `model`, `providers`, `custom_providers`, `fallback_providers` must resolve to loopback,
  RFC1918/ULA, link-local, a single-label LAN name, a `.local`/`.lan`/`.internal` name, or a host in
  `ARIADNE_ALLOW_HOSTS` (for a named gateway on the LAN);
- a provider name from the cloud set (`openai`, `anthropic`, `openrouter`, ...) with **no** `base_url` is a
  violation, because it would use the vendor's endpoint;
- a non-empty `api_key`, or a `key_env` whose variable is set, is a violation.

`ARIADNE_HOME`, never the inherited `HERMES_HOME`, decides which config is checked: run from inside another Hermes,
`HERMES_HOME` points at the assistant's home. That home in this environment *does* carry an `openrouter.ai` endpoint;
Ariadne must never launch against it, and `local-only` now proves it does not.

`plugins/offline_guard` is the old rule (all egress blocked) and contradicts this one; it is disabled and should be
deleted rather than re-enabled.

## Messaging is a conversation, not a door

A messaging conversation is a **session**, exactly like a chat: it may talk and it may submit a task, and the task
continues that session. It gets no tools and no separate home. `ariadne_gate` was the interim hook for this; it is
retired (B14) - the chat home is launched with only the task verbs, skills, clarify and read-only search, so there is
no doing-tool to refuse. A messaging integration that provisions its own tool-enabled home breaks the flow and is
not supported.

## Scheduled jobs are scheduled durable tasks

**Built (B11):** the row lives in the store (`schedules`), `service.schedule_create(session, cron, brief, overrides)`
inherits the session's flow, model, workspace and gates, `schedule.sweep()` runs in the worker's serve loop and
submits a normal `source="schedule"` task per due occurrence, and a refused submission disables the schedule instead
of retrying forever. `ariadne schedules` lists/switches them; the MCP door has `create_schedule`/`list_schedules`.

A schedule is a **standing brief**, not a separate kind of work:

```yaml
# .ariadne/schedules.yaml (or the schedules table; same fields)
- name: nightly-tests          # also the session name: runs continue one chain
  cron: "0 2 * * *"
  brief: "run the full suite and fix regressions it finds"
  flow: coding
  model: qwen3.6-35b-a3b
  workspace: C:/repos/proj
  gates: ["run: pytest -q"]
  enabled: true
```

- Creating a schedule goes through the same backbrief and sign-off as a task: **that is the standing authorisation**
  for every future run, including model downloads it names.
- Each due occurrence calls `service.submit(source="schedule", session=<name>)` and is a normal task: same lifecycle,
  same gates, same report. It appears in the inbox like any other.
- Runs share the schedule's session, so a nightly job accumulates context in one chain instead of starting cold.
- A failed run goes to `needs_attention`; the schedule does not silently retry forever (that is what the task's own
  retry policy is for).
- The scheduler is the worker's serve loop (one process, one model at a time); no separate daemon.

## Capabilities

The desktop's Capabilities screen (`/capabilities`) is where providers, MCP servers and plugins are configured. It is
outside the flow and must not be reachable. The supported mechanism is a route contribution owning that path, which
is what the plugin API's `routes` area is for; **verify route precedence on launch before claiming the lock** - the
shell renders its own tile at that path, and a plugin route that loses the match is decoration. Until that is
confirmed, the provider guard above is the containment: configuration made there still cannot start a model.

## Open questions for the person

- **Per-step models**: keep them as an explicit chain of sessions, or make the model a property of the task only?
  The reset assumes the latter is the default and the former is opt-in.
- **The chat's job**: compose-and-submit only, or also answer questions about a running task from the store? The
  latter needs no doing tools and is cheap.
- **Gates as data**: `run:` commands plus review outcomes is enough, or do gates need a verification recipe per
  flow (`pytest`, `mmdc render`, image dimensions) that the plan must pick from a closed set?
