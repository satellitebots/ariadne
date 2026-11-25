# Gap analysis: the session/task model and the two surfaces

> **Superseded (2026-11-24, by `docs/DESIGN.md`).** Sessions as hosts and the two-contract split are replaced by one
> front, the task/run split and the machine broker. Kept for history.

Supersedes the earlier B12-centric gap analysis. This one is about what is actually wrong now: sessions and tasks are
conflated, and the two entry surfaces have never been given their different contracts. The model, stated once:

- **A session is the host, not a task and not a gate.** It is the durable context a person lives in: a name, the
  workspace work happens in, the flow and model as *defaults* for the tasks it hosts, and the memory/handoff that
  carries between tasks. It has **no QA gate of its own and no execution of its own**. One session hosts many tasks.
- **A task is the drill.** Defined first (brief -> backbrief -> sign-off), then executed step by step by the worker,
  gated per task, reported per step. It is the durable unit that runs, retries, and finishes.
- **The GPU handoff.** The defining model plans, then **sleeps**; the worker takes the full card. Limited VRAM means
  the planner and the worker are never resident together. This is an optimization, not an afterthought.
- **Two surfaces, deliberately different contracts:**
  - **MCP** (a foreign agent, e.g. Claude): **one task at a time.** A connection may create a **disposable session**
    to interactively define the durable task; that task then executes step by step and **each step is reported back**
    over MCP. The connection never "lives in" a session; it drives tasks.
  - **Direct** (console / chat / UI): the **home**. A session with current and past tasks, a conversation that
    continues across them, work done the same modular way - defined first, then the defining model sleeps and the
    worker runs - with no "one task at a time" ceiling.

## Where the code contradicts the model

| # | Contradiction | Evidence today |
|---|---|---|
| 1 | A nameless task spawns its own session | `store.submit` docstring: "default: one session per task"; the fallback is the task id itself |
| 2 | A session cannot hold its own defaults | the `sessions` table has no `workspace` / `model` columns; it inherits whatever the last task used |
| 3 | No session without a task, no view of one, no "another task here" | no `define_session`, no `sessions_show`; the surfaces fuse "new session" and "new task" |
| 4 | The queue is not ordered | `claim_next` orders by `updated`, so any touch reorders the backlog |
| 5 | MCP is poll-based and session-less | `wait_task` polls; no disposable-session define flow and no per-step push channel - the "reported back through each step" contract is not met |
| 6 | The direct UI is a configuration form, not a home | `docs/UI-DIRECTION.md` lists it: three equal columns, form-first, status pills, chat buried, decision buried, mouse-only |

## What is right and must not be rebuilt

The worker and orchestrator (plan, backbrief, sign-off, gates, retries, per-link chains, wall-clock, `timed_out`), the
store (minus schema and ordering), `service`/`present`/`protocol`/`render`, the four MCP servers, the runtime runner
and the restored Hermes backend, `serving`, `watchdog`, `local_only`. The GPU handoff exists (`vram` unload after
sign-off); it needs a test that pins it, not a rebuild.

## Corrected order

1. **Session-as-host in the schema and service.** Add `workspace` and `model` to `sessions` (defaults, not gates);
   `define_session`, `sessions_show`; `submit` joins an existing session and never spawns; kill the tid fallback;
   `claim_next` by `created`. Acceptance: one session row holds N tasks.
2. **The MCP contract.** A disposable session to define the durable task interactively, then step-wise reporting (a
   callback/event channel, not polling). One task at a time, as it already is.
3. **A test that pins the GPU handoff.** At sign-off the defining model unloads and the worker runs alone; assert the
   `vram` event and that planner and worker never co-reside.
4. **The direct UI, rebuilt as a home** (the four steps in `UI-DIRECTION.md`), the session as host, the task as the
   document.
5. **Queue truthfulness.** Reconcile the nine stale backlog rows against what is actually built.
6. **Doc convergence and the wiki rewrite** (`CONVENTIONS.md`, supersession banners, the six stale pages).

Each step lands with tests; steps 2 and 4 are where the two contracts stop being one code path.
