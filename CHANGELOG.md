# Changelog

## 0.1.2 (2026-11-20)

**Sessions are hosts, tasks are executions.** A session is a durable workstream with its own pivot (flow, model,
workspace defaults); a task is one pass through the worker inside it, and many tasks share one session.
`define_session` and `sessions_show` make that explicit; a nameless task no longer spawns its own session, and the
worker claims the oldest-created task so the queue cannot be silently reordered.

**One model, one thing.** With `orchestrator_resident` off (the default), creating a session or task while the
worker runs is refused ("hardware occupied ..."), and interrupt → park → listen is the only way to steer a running
task. The flag (machine-local config, `ariadne/settings.py`) opts into a resident planner for parallel sessions.

**MCP reports through each step.** New `wait_step` walks a running task event by event (plan, step, job, gate,
report) instead of one coarse wait for the end; the drill text tells clients to use it.

**UI rebuilt from scratch.** The console is now a React + Vite + TypeScript app (served by FastAPI): session rail,
task stream, a task document with phase rail and sticky decision bar, composer, inbox and command palette. The
busy gate and the API are the same backend — the UI is a view over it.

**Determinism and consistency.** Inbox labels are truthful (`QUEUED / RUNNING`, `STOPPED, NO WORKER`); the queue and
the docs were reconciled; one status vocabulary (`present.STATUS`); `docs/CONVENTIONS.md` pins the authority order
and supersession banners mark the stale documents; the wiki was rewritten to match; line endings are LF in the index
via `.gitattributes`.

Fixes in this window also include the watchdog refusing to unload a model under a running task, and a process-group
kill switch with a single surface contract for threaded tool servers.

## 0.1.1 - the workflow release

Gates are proposed (never demanded), four retries (not ten rounds), steering, optional workspace, and chat as the
intake surface.

## 0.1.0 - initial release