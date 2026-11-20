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
| B1 | `timed_out` and the task wall-clock | done `c334e8e` |
| B2 | Wire `watchdog.py` into `serve` | done `41784f9` |
| B3 | Route inference through the active model server | done `0d08556` |
| B4 | `worker.py`: one session per task | done `3679767` |
| B5 | `store.py` extraction | done `c3c4cec` |
| B6 | MCP servers `data`, `office`, `ci`, `rag` | done `e2d657f` `d65956e` `3221d29` `6156d19` |
| B7 | `diagram`: draw.io export | done `87b4d66` |
| B8 | Content flow: reference-based generation | done `cc8c1c9` |
| B9 | `ariadne/server` + `ariadne/ui` | done `0e70f97` |
| B10 | Our own chat | done `0d8facd` |
| B11 | Schedules from sessions | done `5ec4891` |
| B12 | Own runtime (frame + drill) | done `e19dffc` … `a8dd137` `45083f1` `c4a65f7` `734fe6d` `4bb9374` (flip) |
| B13 | Install and doctor for the new dependency set | done `18502c0` |
| B14 | Retire `ariadne_gate` | done `84de034` |
| B15 | Wiki rewrite | **not started** (see below) |
| B16 | Model index: device scan + shortlist | done (targeted tests; suite after B12.5) |
| B17 | Hermes is the worker backend (correction) | done `4598aec` |
| B18 | Overlay: own only what we must | done (295 passed) |

Suite: **127 tests at the start, 281 now** (the four gate tests went with the deleted plugin). Every commit above was
made with the suite green; every claim below is a command that ran, not a reading of the code.

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

**B6b `office` — DONE.** `ariadne/office_mcp.py`, stdlib only (`zipfile` + `xml.etree`): a docx/xlsx is a zip of
XML, so no python-docx, no openpyxl, no Office. The document side takes Markdown - headings become real Word styles
(navigation pane works), bullets/numbers/code/pipe tables become paragraphs and tables, `**bold**` and `` `code` ``
become runs - because Markdown is what the design and content flows already produce. The sheet side takes explicit
rows and keeps types (int/float/bool/text, inline strings), with multiple sheets, cleaned sheet names, and a reader
that resolves the sheet list, relationships and shared strings. Absolute paths only; every failure returns as text.
Registered in `flows/mcp_servers.yaml`; enabled for `design`, `investigation` and `content` per `docs/COVERAGE.md`.
Tests: `ariadne/tests/test_office_mcp.py` -> 6 passed (a written document is read back through the same parser, so
the round trip is real, not a byte match). Full suite **175 passed in 89 s**.

**B6c `ci` — DONE.** `ariadne/ci_mcp.py`: three providers behind four verbs (`ci_pipelines`, `ci_status`,
`ci_trigger`, `ci_logs`) - GitHub Actions (workflow dispatch, runs, the logs zip), GitLab (pipelines, jobs trace) and
Jenkins (build / buildWithParameters, builds json, consoleText). Pipelines are named in `.ariadne/ci.yaml`
(gitignored); the entry stores `token_env`, never the token, so copying the file cannot leak a secret. Log output is
trimmed to a tail on purpose: the point is not to pour a 40 MB log into a 9B model's context. A redirect that leaves
the host drops the Authorization header (GitHub sends logs to a signed URL). No network in the tests: a loopback stub
serves all three providers, so the request paths, bodies, auth headers and parsers are real.
Registered in `flows/mcp_servers.yaml`; enabled for `coding` (p80 CI). Tests: `ariadne/tests/test_ci_mcp.py` -> 11
passed. Full suite **186 passed in 92 s**. Named gap: none of the three has been driven against a live server - that
needs the person's URL and token, and is on the deferred list with the GPU work.

**B6d `rag` — DONE.** `ariadne/rag_mcp.py`: ingest (text files or folders, paragraph-first chunking with overlap,
re-ingest replaces a file's chunks), embed (the one model call: the active server's `/embeddings`, batched, idempotent),
search (cosine over float32 vectors in sqlite), and `rag_eval` - recall@k and MRR against labelled questions with a
`min_recall` threshold and a pass/fail. That is the gate `docs/COVERAGE.md` demands ("a RAG gate is a number,
`recall@5 >= 0.8`, not 'it runs'"). Embeddings are the only live dependency; the tests drive a loopback stub with a
four-word vocabulary, so the vectors, cosine, ranking and recall are real and only the model is fake.
Tests: `ariadne/tests/test_rag_mcp.py` -> 8 passed. Full suite **194 passed in 97 s**.

**B6 complete.** Four servers, four dependencies-free modules (`data`, `office`, `ci`, `rag`), registered in
`flows/mcp_servers.yaml` and enabled where coverage says: coding gets `data`, `ci`, `rag`; design, investigation and
content get `office`. Named gaps: parquet needs pyarrow; no provider has been driven against a live Jenkins/GitHub/
GitLab; no embedding model has been loaded (the stub stands in). All three are on the deferred list.

### B7 — `diagram`: draw.io / diagrams.net export

## What remains, and why it was not started

### B12 — Own runtime: rebuild, not graft

The original item (vendor the pin, delete one subsystem per commit) was measured and rejected: `agent/` alone is 468
modules / 162,839 lines, and "delete one subsystem per commit" has no bottom. The instruction was to implement the
server if that is cheaper, and it is: `ariadne/runtime/` is 363 lines and owns the loop.

**Done.**
- `ariadne/runtime/` - `model.py` (one OpenAI-compatible call with tools), `tools.py` (read/write/patch/search/list/
  terminal, a workspace jail, plan-phase read-only enforced at dispatch), `session.py` (resumable message lists),
  `loop.py` (96 lines; turn and time budgets).
- `worker.runtime_run` - the same contract as `hermes_run` (prompt in, report out, session to resume), returning 124
  for out-of-turns/time so the worker's existing "not failure, let the gates decide" rule applies unchanged.
- `ARIADNE_RUNTIME=own` selects it; `Worker` recognises it as a real runner for jobs/KV/unload purposes.
- The drill: `tests/test_runtime_drill.py` runs brief -> plan -> sign-off -> execute -> gates on the runtime with
  `HERMES_EXE` pointed at a path that does not exist, and a tool call that writes a real file.

**Verified.** `pytest ariadne/tests/test_runtime.py` -> 12 passed; `test_runtime_drill.py` -> 1 passed; full suite ->
**247 passed in 118 s**. No model loaded. The drill's scripted model makes one `terminal` call and no MCP/skill/web
call, so it proves the loop, the phase split, the gates and the jail - not that a real coding task can be done. That
distinction is the core of `docs/GAP-ANALYSIS.md`.

**B12.3 — MCP in the runtime — DONE.** Delegated to a subagent (`qwen/qwen3.8-27b`, OpenRouter) with the file map and
acceptance commands; QA'd here (diff read, targeted and full suites re-run, no orphan server processes). 
`ariadne/runtime/mcp.py` gives the runtime a `Pool`: one thread, one asyncio task owning every `AsyncExitStack` (anyio
cancel scopes are task-bound, so a per-call `run_coroutine_threadsafe` fails), a queue bridge into the sync loop,
`mcp__<server>__<tool>` namespacing, schemas from each tool's `input_schema`, and read-only filtering by the flow's
`plan_tools` - data the repo already carried, not a guess at which names mutate. `flows.mcp_server_config()` exposes
the expansion `compile_flow` already did, without writing a home; `loop.run(mcp=...)` merges the pool's tools and
routes `mcp__` calls; `runtime_run` opens the pool for the flow's servers, closes it in a `finally`, and says so in the
report when a server will not attach. 5 tests against the real `data` server over stdio (schemas, a real profile call,
plan-phase refusal, a bad command that errors without hanging, the worker wiring). Suite: **252 passed**.

**B12.4 - skills as runtime tools - DONE.** `ariadne/runtime/skills.py` gives the loop the two reads a worker needs:
`skills_list` (one line per skill, description from the SKILL.md frontmatter) and `skill_view` (the body, capped at
8000 chars), resolved through `flows.shared_skill_dirs` so `skills/common` and the flow's own folder both count. The
plan prompt already carried the index; this is what lets a run follow a skill instead of only knowing it exists.
`loop.run(skills=...)` merges the two schemas and routes the names; `runtime_run` builds the box. 7 tests with a
tmp skill tree (list, view, unknown name, cross-flow lookup, loop dispatch, worker wiring). Suite: **259 passed**.

**B12.5 - web search - DONE.** `ariadne/runtime/web.py` adds the tool the plan prompts already named: one `web_search`
schema, DDGS behind an injectable transport, the limit clamped to 1..10, snippets flattened to 300 chars, and every
failure (rate limit, dead network) returned as text. `loop.run(web=...)` merges it and routes the name; `runtime_run`
passes a `Search`, which holds no server and needs no close. 8 tests, all network-free. Suite: **277 passed**.

**B12.6a - context trimming and the per-run log - DONE.** A long run used to grow its message list without bound. Now,
before every model call, a list estimated over `context_tokens * trim_at` is cut to the system message plus a
contiguous tail taken from the end (`_trim_messages`), and the boundary is repaired so a `tool` result never outlives
the assistant call it answers and a call is never kept without its results; the system message says how many messages
were omitted (the note is replaced, never duplicated), and the trimmed history is what the session saves. `Answer.dropped`
counts the loss. `runtime_run` also writes the artifact the old path wrote: `.ariadne/logs/<tid>-<phase>-<epoch>.log`
with the flow/phase/model/session/workspace header, the prompt, each tool call, the report and the stop reason; an
unwritable log is swallowed so a full disk cannot fail a task. 4 tests (trim under budget, no trim under it, resume
order, the log file). Suite: **281 passed**.

**B12.6b - todo, park and the MCP markers - DONE.** Three gaps between the runtime and `hermes_run` closed:
`todo_write` (a `- [ ]` checklist at `<workspace>/.ariadne/todo.md`, refused in read-only phases like every write);
the park boundary (`loop.run(checkpoint=...)` is asked after each finished turn, never on the first, and stops with
`stopped="parked"`, which `runtime_run` maps to exit 125 so `Worker.run` holds and resumes the same session; side
phases never park); and the markers `jobs_mcp` reads (`ariadne_task`, `ariadne_workspace`, `ariadne_phase`, written
into the flow home before the pool starts). KV needed no runtime code - `Worker.run` already restores and saves around
any runner, which is now stated in the docstring. 8 tests. Suite: **289 passed**.

**B12.7 - the flip - DONE.** The worker's default runner is `runtime_run`; `hermes_run` and its helpers
(`_clean_output`, `_kill_tree`, `_turn_end_reason`, `_latest_session`, `stop_gateway`) and the gateway stops are
deleted. Out of turns is exit 126, out of time 124, parked 125, so the worker's three tolerances survive without
scraping a Hermes log. The flow no longer compiles a Hermes home: `compile_flow`, `BASE_CONFIG`,
`install_shared_skills` and `compile_all` are replaced by `prepare_homes()` (mkdir only) and `mcp_server_config`;
skills are read from the repo directly. `pyproject.toml` now carries Ariadne's real dependencies and `install()` syncs
the venv from it instead of from the Hermes project. `deps.submodule_pin`, the doctor submodule check, the
`test_hermes_contract` suite and the `upstream/` submodule (with `.gitmodules`) are gone. Tests that asserted compiled
homes were rewritten to assert the runtime's config, the catalog window and `serving.endpoint()`. Suite: **281 passed**
with no submodule and no `hermes` binary.

**B12.8 - the chat on the runtime - DONE.** `chat.run_turn` runs on `runtime.run(..., native_tools=False)` with the
`ariadne_tasks` MCP server and `web_search`; the file, patch, search-in-files and terminal tools do not exist in that
conversation, so the rule is construction rather than a hook. `compile_home`, the `hermes chat` launch and the toolset
list are deleted; `ariadne chat` is a terminal loop over the same `ask()`. 6 chat tests, rewritten to assert
`native_tools=False`, the chat system prompt and the tasks server. Suite: **281 passed**.

**Queue empty.** B12.1-B12.8 are done: the frame, the drill, MCP, skills, web search, trimming and logs, todo/park/
markers, the flip and the chat. B15 (the wiki rewrite) is the last backlog item. The counted capability matrix and the
three root causes that produced this queue are in `docs/GAP-ANALYSIS.md`.

### B16 — Model index: what this machine can run

**What was missing.** The catalog (`serving/models.yaml`) carried a size for every model, but nothing turned the
machine into a verdict: `Catalog.fits()` compared size against one budget number, `deps.gpu()` only asked whether
`nvidia-smi` existed, and no surface said which models this box can actually run or why.

**What changed.**
- `ariadne/modelindex.py`: `scan()` (GPU/VRAM, RAM, CPU, cores, backend, free disk; every probe injectable),
  `capacity()` (the VRAM tier and the profile's total), `verdict()` (`gpu` / `hybrid` / `no`, arithmetic in the
  reason), `available()`, `report()`, and `pulse()` - Hugging Face's most downloaded models per task, estimated at
  q4 from the reported parameter count, filtered by the same rule and cached for a day.
- `models.OVERHEAD_GB = 1.5` (KV at 64K + CUDA context + buffers) and `Catalog.fits()` now uses it, so the planner's
  menu and the index apply one rule.
- `resources.detect_at_boot()` logs `models: N of M can run here (K fit in VRAM)` at every startup; `ariadne models
  index [--json] [--pulse ...] [--refresh]` prints it on demand.

**Verified.** `pytest ariadne/tests/test_modelindex.py ariadne/tests/test_models.py` -> 23 passed. Live run on this
machine: `device: RTX 3070 Laptop, 8 GB VRAM, 31.9 GB RAM`, 4 models `gpu` (qwen3.5-9b at 7.1 GB just fits), 6
`hybrid` (qwen3.8-27b 19.2 GB, qwen3.6-35b-a3b 23.9 GB), none `no`; the pulse returned 10 real models within the
machine's budget. Startup line confirms `10 of 10 can run here (4 fit in VRAM)`.

**Deliberately not done:** pulse hits are never added to the catalog. The catalog is a closed set; admitting a
suggestion is the person's decision.

### B17 — Hermes is the worker backend (correction to B12.7)

**What went wrong.** B12.7 read "implement the server if it is cheaper" as permission to replace the agent backend.
The intent was the opposite: Ariadne orchestrates, Hermes does the agent work, and only the surfaces with the wrong
hook (desktop app, chat, MCP hosting) are ours. The flip also broke the venv's `hermes` install, which had been an
editable install pointing at the deleted tree.

**What changed.** `vendor/hermes` is a submodule at `458a0046…`; the venv is rebuilt from its lockfile
(`uv sync --project vendor/hermes --frozen --extra mcp --extra ddgs`). `hermes_run` and its helpers,
`flows.compile_flow`/`BASE_CONFIG`/`install_shared_skills`/`compile_all`, `deps.submodule_pin`, the doctor submodule
check, `paths.UPSTREAM` and `test_hermes_contract.py` are restored, and `hermes_run` is the default runner again.
`ARIADNE_RUNTIME=own` selects `runtime_run`, which stays as the fallback and the model-free test path.

**Not restored, deliberately:** the desktop app, the chat and the MCP hosting surface stay ours — those are the parts
whose integration points belong to the orchestrator. The chat runs on the own runtime with `native_tools=False`.

**Verified.** Two tests pin the decision (default runner is `hermes_run`; `ARIADNE_RUNTIME=own` selects the runtime).
`hermes.exe --version` reports v0.23.2 at the pin and `import run_agent` resolves; the full suite is **289 passed**. A plain `pip install hermes-agent` from git is impossible at this pin
(pillow/browser-harness conflict), which is why the checkout + lockfile is the supported form.

### B18 — The overlay

**What it is.** `vendor/hermes` stays a pristine submodule; Ariadne overlays it. `overlay.install()` puts repo root,
then `vendor/hermes`, then site-packages on `sys.path`; `overlay.extend(pkg)` prepends `overlay/<pkg>` to that package's
`__path__`, so a module we own wins and every other module still comes from the submodule. `overlay.yaml` is the ledger
(module, why, test) and `overlay.check()` fails the suite when an entry has no file, reason or test. `tools/sync_hermes.py`
does the update: fetch, checkout, stage the pointer, rebuild the venv from the submodule's lockfile.

**Why this shape.** Subtree would have dragged 163k lines into our history and made every diff noisy; a root merge
would have broken Hermes's absolute imports. The overlay owns only what must differ and keeps a pin bump to one
`git add vendor/hermes`.

**Verified.** 6 overlay tests (idempotent order, an overlaid module winning while the rest stays upstream, `apply()`,
a package without an overlay untouched, the three ledger failures, the real ledger consistent). Suite: **295 passed**.

**Deliberately empty.** No real override yet; nothing needs to differ at code level. The runtime gut is config
(toolsets, plugins, telemetry, catalog, no gateway/desktop/bots), so the ledger starts empty and the first override
will arrive with its test.

### B15 — Wiki rewrite (not started)

Six stale pages (Flows-and-Skills, Models-and-Resources, Concepts, Architecture, Decisions, Status-and-Roadmap), then
delete `Desktop.md`, then publish with `tools/publish_wiki.py`. The rewrite is ~600 lines of documentation that has to
agree with twelve commits' worth of change; it is a unit of work on its own, and publishing pushes to
`satellitebots/ariadne.wiki.git`, which needs the person's network and credentials. `python tools/publish_wiki.py
--dry-run` is the local check available before that push.

## Notes for whoever picks this up

- The console is the fastest way to see the state: `python -m ariadne ui`, then `http://127.0.0.1:8787`.
- Model-free verification is the whole loop: `pytest -q`, `python -m ariadne flows`, `inbox`, `doctor`, `schedules`,
  `local-only`. Nothing above was proved by loading a model.
- The deferred list in `docs/BACKLOG.md` (a first end-to-end flow run, watchdog thresholds under load, a live CI
  provider, a live embedding model, the LAN smoke test) is still the honest boundary of what is proven.

## Workflow fixes (post-0.1.0)

- B19 gates proposed by the planner; submit no longer waits in awaiting_gates. 2 tests.
- B20 max_iterations 5 (1 run + 4 retries).
- B21 steering (store/service/CLI/MCP -> next execute prompt), optional workspace with session memory, chat intake
  collects flow/model/workspace/gates and hands off.
- Suite: 301 passed.
