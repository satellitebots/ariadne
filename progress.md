# Progress

A working log of the backlog sweep. One item at a time, in `docs/BACKLOG.md` order, each with its own tests and
commit. This file is the tracker; `docs/BACKLOG.md` stays the queue and moves each finished item to **Done**.

Started: 2026-11-19. Repo: `C:/repos/ariadne`, branch `main`, clean tree at `f57ae39`.
Baseline: `.venv/Scripts/python.exe -m pytest -q` → **127 passed in 66.94s**.

## Situation

The six docs agree on the target and disagree with parts of the code, which is expected: the docs are the authority
and the code is legacy to migrate (`docs/DESIGN-RESET.md`). What is already true:

- One rulebook (`service.py`), one document (`present.py`), one plan format (`protocol.py` + `render.py`).
- Local-only inference enforced at every command that can start a model (`local_only.py`).
- A model-server abstraction exists (`serving.py`) but the worker does not use it yet (B3).
- The watchdog exists (`watchdog.py`) but nothing starts it (B2).
- The worker still spawns `hermes chat -z` per step group (B4); the store still lives inside `orchestrator.py` (B5).
- No own frontend, no own chat, no schedules, no `data`/`office`/`ci`/`rag` MCP servers (B6, B9–B11).

What the docs ask for that the store cannot express today: `timed_out` (B1), the watchdog wired to real callbacks
(B2), the active server used for inference (B3), one session per task (B4).

## Order and status

| # | Item | State |
|---|---|---|
| B1 | `timed_out` and the task wall-clock | in progress |
| B2 | Wire `watchdog.py` into `serve` (built, unwired) | queued |
| B3 | Route inference through the active model server | queued |
| B4 | `worker.py`: one session per task | queued |
| B5 | `store.py` extraction | queued |
| B6 | MCP servers `data`, `office`, `ci`, `rag` | queued |
| B7 | `diagram`: draw.io export | queued |
| B8 | Content flow: reference-based generation | queued |
| B9 | `ariadne/server` + `ariadne/ui` | queued |
| B10 | Our own chat | queued |
| B11 | Schedules from sessions | queued |
| B12 | Runtime fork strip | queued |
| B13 | Install and doctor for the new dependency set | queued |
| B14 | Retire `ariadne_gate` | queued |
| B15 | Wiki rewrite | queued |

Deferred by the docs (needs the GPU or a live model): a first end-to-end flow run, watchdog thresholds under real
VRAM pressure, retrieval-quality gates for B6d. Those stay deferred here too; everything below is verified model-free.

## Log

### B1 — `timed_out` and the task wall-clock — DONE

**What was missing.** `FINAL` had four statuses, so no task could end `timed_out`; there was no wall clock at all
(the two existing bounds were per-run `run_budget` and per-task `max_iterations` rounds).

**What changed.**
- `orchestrator.py`: `timed_out` joined `FINAL`; `tasks.run_started` (schema + migration for old stores); the claim
  starts the clock, so time waiting in the queue or for a sign-off is not charged; `Worker(clock=...)` so a test can
  spend time; `_expired()` checked at the top of every execute attempt and again after a run returns, before QA;
  `_out_of_time()` ends the task honestly.
- `flows.py` + all four `flow.yaml`: `task_budget` (coding 4 h, design 3 h, investigation 2 h, content 1.5 h;
  0 = no task-level limit).
- `present.py` + `console.py`: the status label (`out of time`) and its mark; `tasks_mcp.py`: what the caller is told
  to do next.

**The rule implemented** (from `docs/COVERAGE.md`): out of wall-clock is not failure. No further model work runs;
the workspace is kept; the gates a script can run are run. All pass and nothing needs a reviewer -> `done` (with a
note that the clock was spent). Anything else -> `timed_out`, and the result names the failing gates and the review
gates that were *not reviewed* rather than guessing a verdict.

**Verified.** `pytest ariadne/tests/test_timeouts.py` -> 8 passed; full suite -> **135 passed in 81 s** (127 before,
8 new). `python -m ariadne flows` compiles all four flows; `python -m ariadne inbox` prints state without a model.
Not proved: a real 4-hour run against a live model - that is on the GPU-deferred list.

**Notes / drift seen.** `console.LABEL` is a second copy of `present.STATUS` (the design says only `present` styles a
task). B1 added the new status to both; the duplication should die with the frontend work (B9), not now.
`inbox` lists `new` tasks under RUNNING even with no worker; `stale` only catches `planning`/`executing`. Worth
fixing when the console is reworked.

**A finding worth recording:** the real store already holds 15 queued tasks submitted earlier today with
`source="backlog"` (B1-B13), each with `run=<pytest>` and a doc gate. They were never claimed. They duplicate this
sweep, and a started worker would run them on the GPU. B1's own row was closed with `cancel` plus an event naming
this commit; the rest are being closed item by item as the same work lands here.

### B2 — wiring the watchdog into `serve` — DONE

**What was missing.** `watchdog.py` had the sampler and the ladder, but nothing started it; `serve` (the worker loop)
knew nothing about it.

**What changed.**
- `watchdog.py`: `server_url()`, `unload_model()` (llama-swap `/unload`), `kill_server()` (`serve.stop()`),
  `flag_tasks(store, why)` (every `planning`/`executing` task -> `needs_attention` with the readings and an event),
  and `start(store, ...)` - one daemon thread, every callback injectable, `stop()` for the finally block.
- `Watchdog.check`: at the top rung the action runs once. It used to re-run `flag` every sample for as long as the
  machine stayed bad; now the row is still logged (with `repeat: true`) and the callback is not called again.
- `orchestrator.serve`: `_watchdog(w.store)` starts it right after `_reconcile`, and the `finally` stops it.

**Verified.** `pytest ariadne/tests/test_watchdog.py` -> 10 passed (5 new); full suite -> **140 passed in 82 s**.
The thread test escalates for real against a fake sampler and injected callbacks, so no GPU and no kill path runs.
Not proved: the thresholds under real VRAM pressure - deferred, needs the GPU (`docs/BACKLOG.md`).

### B3 — route inference through the active model server — DONE

**What was missing.** `serving.py` could register and probe a server, but every actual model call used the hardcoded
`paths.LLM_BASE_URL` (8090) or its own guess: `llm`, `kvcache`, `image_mcp`, `jobs.unload_models`, and the compiled
flow homes. So `ariadne server remote http://gpu.lan:11434` changed what `ariadne server` *reported* and nothing
else. The committed registry also said llama-server was on **8080** while `serve.start` listens on **8090**.

**What changed.**
- `serving.endpoint()` (…/v1) and `serving.base()` (no /v1) are now the single answer to "where is inference", and
  they run `check_url` on whatever they return - including an explicitly passed server and `ARIADNE_LLM_URL`.
- `llm`, `kvcache._post`, `image_mcp._free_gpu`, `jobs.unload_models`, `watchdog.server_url`, and
  `flows.compile_flow` (primary **and** fallback provider) all read it. A compiled flow home now carries the LAN
  address, so Hermes itself goes there.
- `serve.start` starts our llama-server only when that is the active kind; for `ollama`/`remote` it checks the
  endpoint answers and refuses loudly if not. `serve.stop` will not touch a server that is not ours.
- `orchestrator.serve` re-checks `local_only.check_home()` before it takes the worker lock.
- `serving/servers.yaml` + `serving.DEFAULT`: 8080 -> 8090, matching where we listen.

**Verified.** `pytest ariadne/tests/test_serving_routing.py` -> 11 passed against a loopback stub HTTP server (chat,
health, KV save, unload all arrive at the active endpoint; a cloud URL is refused; `serve` does not spawn our binary
for a LAN server). Full suite -> **151 passed in 96 s**. Not proved: a live smoke test against a real LAN box -
deferred with the GPU items.

### B4 — `worker.py`: one session per task — DONE

**What was missing.** Execution lived in a 1,482-line `orchestrator.py` and spawned a run per *step group*: every
model change started a new Hermes session, and every failed gate was preceded by a checkpoint, so each retry began
from a compressed summary instead of the session that had just done the work. That is the "second agent runtime"
the design reset calls out.

**What changed.**
- New `ariadne/worker.py` (1,009 lines) owns execution: the runner, the prompts, the model plan, the `Worker`.
  `orchestrator.py` is down to **620** lines (store, serve loop, CLI) and re-exports the names every surface and test
  already imported. New `ariadne/errors.py` holds `TaskError` so neither module has to import the other.
- The plan records `models.chain`: consecutive steps one agent model owns share a session; a generate/image step is
  not a session (the agent calls it as a tool). It is printed in the backbrief ("2 sessions (a session per agent
  model...)") and rewritten when `apply_model_overrides` changes a model.
- `execute()` runs each link of the chain once and runs the gates **after the last one**; a failing gate resumes the
  same session with `RETRY_PROMPT` (only the failures), bounded by `max_iterations` and the no-progress rule. No
  checkpoint between attempts, so the context survives; a checkpoint still closes each link for the next model.
- `step_groups` and `agent_for` are deleted. `parse_model_plan`/`model_summary`/`model_block` stay, now chain-aware.

**Verified.** New `pytest ariadne/tests/test_worker_session.py` -> 4 passed (resume asserts the *same* session id and
that no compression happens between attempts; the chain test asserts the recorded `models.chain` and the
"NOW DO STEPS 2, 3 ONLY" scope). Full suite -> **155 passed in 96 s**. `ariadne flows`, `inbox` and `local-only` still
run model-free. Not proved: a live run against a real model (deferred with the GPU items).

**Also fixed here:** `park.resume()` retried instead of raising `WinError 32` when another thread is reading the flag
file. It surfaced as a flaky `test_browser` failure once the timing shifted; the fix is in the product, not the test.

### B5 — `store.py` extraction — DONE

**What changed.**
- `ariadne/store.py` (301 lines) now holds `Store`, the schema, `FINAL`/`WAITING`, the gate parser and
  `gates_text`. `orchestrator.py` is down to **353** lines: the worker process, the serve loop, the `task` CLI.
  Together with B4 that is 1,482 -> 353 + 1,007 + 301 across three modules with one job each.
- `service.py` is the only caller for surfaces: it gained `task/tasks/wait/feedback/event/open_feedback/
  resolve_feedback/adopt` and every verb takes an optional `store=`, so a surface carries a handle it never uses
  itself. `console.py`, `tasks_mcp.py`, `park.status` and `jobs_mcp` now call service for every read and write;
  `ariadne task …` does too. The only code that touches store methods is `service.py` and `worker.py` (the engine
  recording progress).
- The one gesture (`ariadne "fix the date test"`) is now `service.submit_unrouted`: the single door that does not
  name a flow, spelled out as such. `ariadne task submit` (and the documented `ariadne submit`) requires `--flow`
  and `--model`, the same rule every other door enforces - and `ariadne submit` now actually dispatches instead of
  being swallowed by the one-gesture path (a pre-existing bug: the README documented a command that did not exist).

**Verified.** New `pytest ariadne/tests/test_layering.py` -> 6 passed (no surface module even imports `Store`; the
worker keeps its store; the CLI refuses a task with no flow or no model and exits 2). Full suite -> **161 passed in
89 s**. `ariadne inbox`, `flows` and `local-only` run model-free; `ariadne submit "fix it"` answers "name the flow"
rather than creating a task.

**Not fixed here (named, not hidden):** `Store.approve` still calls `model_summary`/`apply_model_overrides` from
`worker.py` through a lazy import. The sign-off rule belongs in `service.py` eventually; moving it now would change
sign-off behaviour in the same commit that moves files, which B5 was told not to do.

### B6 — MCP servers: `data`, `office`, `ci`, `rag`

**B6a `data` — DONE.** `ariadne/data_mcp.py`, stdlib only: a csv, parquet (via pyarrow when present) or sqlite file
becomes a table in an in-memory SQLite database, so one language covers profile / query / transform. `query` is
SELECT-only, `transform` writes csv/json/sqlite to an absolute path, and every failure comes back as text. Registered
in `flows/mcp_servers.yaml`; enabled for `coding` and `investigation` per `docs/COVERAGE.md`. Named gap: parquet
needs `pyarrow`, which this environment does not have - the tool says so and names the pip command.
Tests: `ariadne/tests/test_data_mcp.py` -> 8 passed. Full suite **169 passed in 89 s**.

**B6b `office`** — (below)
