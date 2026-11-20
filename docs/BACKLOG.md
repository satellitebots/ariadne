# Backlog

The queue. Each item is independently shippable, worked in order, and verified without loading a model unless the
item says otherwise. Done items move to the bottom with their commit. Nothing here is a live task in the store until
it is picked up.

Rules for every item: tests first where behaviour is involved; `upstream/` untouched; no cloud endpoints; the item's
own doc updated in the same commit.

## Queue

### B12 - Own runtime: run a task without Hermes

**Decision (person's instruction, 2026-11-19): rebuild, do not graft.** The pin's `agent/` alone is 468 modules /
162,839 lines; gutting it is unbounded work that diverges from upstream forever. What Ariadne actually uses is one
HTTP call, six tools, a message list and a loop - that is now `ariadne/runtime/`, owned here. This overrides
DESIGN-RESET's "must not own an agent loop": the alternative was owning a 163k-line fork, which is worse.

**Done**
- B12.1 the frame: `ariadne/runtime/` - `model.py` (OpenAI tool calls), `tools.py` (read/write/patch/search/list/
  terminal, a workspace jail, and the plan phase read-only enforced at dispatch), `session.py` (resumable message
  lists), `loop.py` (96 lines, turn and time budgets). 12 tests, no model.
- B12.2 the drill, which is the acceptance test that was missing: `worker.runtime_run` + `Worker(runner=runtime_run)`
  runs a full brief -> plan -> sign-off -> execute -> gates against a scripted model, with `HERMES_EXE` pointed at a
  path that does not exist, and a tool call that writes a real file (`tests/test_runtime_drill.py`).
- `ARIADNE_RUNTIME=own` switches a worker onto it; the default is still Hermes until B12.6.
- B12.3 the flow's MCP servers as runtime tools: `ariadne/runtime/mcp.py` (`Pool` - one thread, one asyncio task owning
  every `AsyncExitStack`, a queue bridge into the sync loop, `mcp__<server>__<tool>` namespacing, schemas from
  `input_schema`, read-only filtering by the flow's `plan_tools`), `flows.mcp_server_config()` (the registry expansion
  `compile_flow` already used, without writing a home), `loop.run(mcp=...)`, and `runtime_run` opening/closing the pool
  and naming a server that will not attach. 5 tests against the real `data` server over stdio; suite **252 passed**.
- B12.4 skills as runtime tools: `ariadne/runtime/skills.py` (`Box` - `skills_list` and `skill_view` over
  `flows.shared_skill_dirs`, descriptions from frontmatter, 8000-char body cap, an unknown name lists what exists),
  `loop.run(skills=...)`, and `runtime_run` passing the box. 7 tests; suite **259 passed**.
- B12.5 web search: `ariadne/runtime/web.py` (`Search` - one `web_search` schema, DDGS behind an injectable transport,
  limit clamped 1..10, snippets flattened to 300 chars, every failure as text), `loop.run(web=...)`, and `runtime_run`
  passing it. 8 tests; suite **277 passed**.
- B12.6a context trimming and the per-run log: past `context_tokens * trim_at` the loop keeps the system message and a
  contiguous tail, repairs the boundary so no `tool` result outlives its call, records the omission in the system
  message, and saves the trimmed history; `Answer.dropped` counts it. `runtime_run` writes
  `.ariadne/logs/<tid>-<phase>-<epoch>.log` (header, prompt, tool calls, report, stop reason) and returns it in
  `RunResult.log`; a full disk is swallowed. 4 tests; suite **281 passed**.
- B12.6b todo, park and the MCP markers: `todo_write` (a checklist at `<workspace>/.ariadne/todo.md`, execute phases
  only), the park boundary (`loop.run(checkpoint=...)` stops a finished turn with `stopped="parked"`;
  `runtime_run` maps it to `PARKED` = 125, side phases never park), and the three markers `hermes_run` used to write
  (`ariadne_phase`, `ariadne_task`, `ariadne_workspace`) so `jobs_mcp` records a job against the right task. KV needed
  no code: `Worker.run` restores and saves around any runner. 8 tests; suite **289 passed**.
- B12.7 the flip: `Worker`'s default runner is `runtime_run`, and `hermes_run`, `_clean_output`, `_kill_tree`,
  `_turn_end_reason`, `_latest_session`, `stop_gateway` and the gateway calls are deleted (out of turns is now exit
  126, out of time 124, parked 125). `flows.compile_flow`/`BASE_CONFIG`/`install_shared_skills`/`compile_all` are gone
  in favour of `prepare_homes()` and `mcp_server_config`; the venv comes from Ariadne's own `pyproject.toml`
  (`mcp`, `fastapi`, `uvicorn`, `ddgs`, `ruamel.yaml`), not from the Hermes project; `deps.submodule_pin` and the
  submodule check are gone; the `upstream/` submodule and `.gitmodules` are deleted. The tests that asserted compiled
  Hermes homes were rewritten to assert the runtime's config and the catalog window. Suite **281 passed** with no
  submodule and no `hermes` binary.
- B12.8 the chat on the runtime: `chat.run_turn` calls `runtime.run(..., native_tools=False)` with the
  `ariadne_tasks` MCP server and `web_search`, so the file/patch/search/terminal tools do not exist in that
  conversation at all; `compile_home`, the Hermes CLI launch and the toolset list are deleted, and `ariadne chat` is a
  small terminal loop over the same `ask()`. 6 tests; suite **281 passed**.

**Left: nothing.** B12.1-B12.8 are done; B15 (the wiki rewrite) is the last item.

### B15 - Wiki rewrite  (done: 847ed0e; publish pending)
The six stale pages rewritten to the authority docs and `Desktop.md` deleted (commit 847ed0e). Publishing
with `tools/publish_wiki.py` remains a separate, manual step - it pushes the wiki to GitHub and is not run
automatically.
## Explicitly deferred (needs a live model or the GPU)

- The first end-to-end run of any flow, and the RAG case-study task still sitting `executing` in the store.
- Load/stress behaviour of the watchdog under real VRAM pressure - the thresholds get tuned then, not before.
- Retrieval-quality gates for B6d.

## Done

- Doctor for the real dependency set (Python, the active server, each flow's needs; Node stays) - this commit
- `plugins/ariadne_gate` retired: the chat has no doing-tools to refuse - this commit
- Schedules: cron rows in the store, inherited per session, swept by the worker - this commit
- Our own chat: a session-bound conversation with no doing-tools by construction - this commit
- `ariadne/server` + `ariadne/ui`: FastAPI, SSE, the static sessions console - this commit
- Content: the reference pack, the citation gate and a fact-check pass - this commit
- draw.io / diagrams.net in the diagram server: export, import, local SVG - this commit
- The four approved MCP servers: `data`, `office`, `ci`, `rag` - this commit
- The store in `store.py`; every surface calls `service`, none call the store - this commit
- One session per task: `ariadne/worker.py`, the plan's `models.chain`, resume on a failed gate - `3679767`
- Inference follows the active server (`serving.endpoint()`; llm, KV cache, image, jobs, flow homes) - `0d08556`
- Watchdog wired into the worker (`_watchdog` in `orchestrator.serve`, real unload/kill/flag callbacks,
  act-once escalation) - `41784f9`
- `timed_out` and the task wall-clock (`orchestrator.py`, `present.py`, flows) - `c334e8e`

- Watchdog: escalation, sampling, jsonl trail (`ariadne/watchdog.py`) - this commit

- Model server abstraction (`ariadne/serving.py`, `serving/servers.yaml`) - `de289ef`
- Approved tool set widened to p90 + coverage/runtime contract - `c7a2425`
- Backend congregation: `service.py`, `present.py`, `protocol.py`, `render.py`; MCP lockdown - `f7b6353`
- Local-only provider lock (`ariadne/local_only.py`) - `f7b6353`
- Frontend pivot: desktop plugin retired - `f7b6353`, `ef04a14`

### B16 - Model index: device scan and a hardware-bounded shortlist

**Done.** `ariadne/modelindex.py`: `scan()` measures GPU/VRAM, RAM, CPU, disk and backend (every probe injectable);
`capacity()` turns the device into "fits in VRAM" and "the most a model may take under the active profile";
`verdict()` gives every catalog model `gpu` / `hybrid` / `no` with the arithmetic in the reason, using one shared
1.5 GB reservation for KV + context + buffers (`models.OVERHEAD_GB`, also used by `Catalog.fits`, so the planner's
menu and the index agree). `report()` prints the device and every tier; `pulse()` asks Hugging Face for the most
downloaded models of a task (`text-generation`, `text-to-image`, `feature-extraction`), estimates a q4 size from the
reported parameter count, filters through the same rule, and caches for a day with `--refresh`. At startup
`resources.detect_at_boot` logs `models: N of M can run here (K fit in VRAM)`.

CLI: `ariadne models index [--json] [--pulse agent|image|embed] [--refresh]`. Tests: 10 in `test_modelindex.py`
(tiers, overhead, MoE reason, CPU-only, report, pulse filter/sort/limit/cache/refresh, network failure, and catalog
agreement), no network except one manual live check of the pulse. Suite: **pending the B12.5 run**.

**Not done, deliberately:** pulse hits are not added to the catalog; admitting a model is a person's decision and the
catalog is a closed set.

### B17 - Hermes is the worker backend (correction to B12.7)

**Done.** The intent was always that Ariadne orchestrates and Hermes does the agent work; B12.7 deleted Hermes and
defaulted to the own runtime, which contradicted that and broke the venv's `hermes` install (an editable install
pointing at the deleted tree). Restored:

- `vendor/hermes` is a git submodule at `458a0046ad6ce75f6f7b2705f592b9c7a749fe14`; the venv is built from its own
  lockfile (`uv sync --project vendor/hermes --frozen --python 3.14 --extra mcp --extra ddgs`), so `hermes.exe` is in
  `.venv/Scripts` again. A plain `pip install hermes-agent` from git does **not** work at this pin (pillow conflict).
- `worker.hermes_run` and its helpers are back, `flows.compile_flow`/`BASE_CONFIG`/`install_shared_skills`/
  `compile_all` are back, and `hermes_run` is the **default runner**. `ARIADNE_RUNTIME=own` selects
  `runtime_run`, which stays as the fallback and as the model-free path the drill uses.
- `deps.submodule_pin`, the doctor submodule check, `paths.UPSTREAM`, and `test_hermes_contract.py` are back.
- Two tests pin the decision: the worker's default runner is `hermes_run`, and `ARIADNE_RUNTIME=own` selects the
  runtime. Suite: **289 passed**, with `hermes.exe` resolving to the pinned checkout.

What stays replaced, because the hook belongs to the orchestrator: the desktop app (our SPA), the chat (our runtime
with `native_tools=False`), and the MCP hosting surface (our servers). Everything else is Hermes's.

### B18 - The overlay: own only what we must, and keep the submodule updatable

**Done.** `vendor/hermes` stays a pristine submodule; Ariadne is an overlay on it.

- `ariadne/overlay.py`: `install()` fixes the import order (repo root, `vendor/hermes`, site-packages); `extend()`
  prepends `overlay/<package>` to a package's `__path__` so our module wins per file; `apply()` does both; `check()`
  validates `overlay.yaml` (every declared module has a file, a reason and a test). `ariadne/bootstrap.py::start()`
  is the one call every entry point makes before it can import Hermes.
- `overlay.yaml`: the ledger. Empty is normal - the runtime gut is configuration, not code.
- `tools/sync_hermes.py`: fetch, checkout a tag/commit, stage the pointer, `uv sync --project vendor/hermes --frozen`.
  Then `pytest -q`; `test_hermes_contract.py` names any CLI flag, config key or hook that moved.
- `pyproject.toml`: `testpaths = ["ariadne/tests"]`, `norecursedirs` excludes `vendor` and `overlay`, so Hermes's own
  suite is never collected.
- Tests: 6 in `test_overlay.py` (order idempotent, an overlaid module wins while the rest comes from upstream,
  `apply()`, a package with no overlay untouched, the ledger's three failure modes, the real ledger consistent).
  Suite: **295 passed**.

No real override exists yet, deliberately: nothing needs to differ from Hermes at code level. The first one gets added
with its manifest entry and its test.



## B19 - Gates are proposed, never demanded (done)

A task without gates used to sit in `awaiting_gates` until a person invented them; an investigation brief rarely has
them, so the request looked rejected. Now `Store.submit` always returns `new`: the plan prompt asks for 1-3 check gates
when none were given, `plan()` adopts them onto the task, and sign-off approves gates and plan together. `set_gates`
still works for a person who wants their own. Covered by `test_a_task_without_gates_starts_and_the_planner_proposes_them`
and `test_the_planner_proposes_gates_when_the_task_has_none`.

## B20 - Four retries, not ten rounds (done)

`Flow.max_iterations` is 5 = one run plus at most four retries. The no-progress rule still stops earlier. The next
slice is a judge: before a retry, ask the worker model whether another attempt is worth it and what must change.

## B21 - Steering, optional workspace, chat intake (partly done)

- `store.steer` / `take_steers`, `service.steer`, `ariadne steer ID "..."`, `steer_task` over MCP. The worker prepends
  the notes to the next execute prompt ("STEERING from the person") and marks them delivered. Delivery is at the next
  step boundary; a note sent mid-link waits for that boundary.
- Workspace is optional: a new task in a session reuses where that session last worked; a new session starts in the
  current folder.
- Chat gathers the details (flow, model, workspace if the person gives one, 1-3 gates, proposing gates itself) and then
  hands off; the chat is the intake surface and the worker runs while it sleeps.
- Still open: a steer box in the console for a running task, and `steer` on the chat's task card.

## B22 - Sessions are durable workstreams

A session is the unit a person lives in; tasks are things that happen inside it. One session -> many tasks, each with
its own plan, gates and report, sharing the session's memory, workspace and Hermes segment. Still open:

- `ariadne sessions show NAME`: the session's tasks, their statuses and the latest handoff, in one view.
- "New task in this session" from the console (the CLI already does it with `--session`).
- A session-level chat that survives tasks: the conversation continues across tasks, and submitting from it does not
  end it.


### Step 3 (GPU handoff pin) - covered, no new code
`test_the_orchestrator_model_is_unloaded_before_execution` (test_discrepancies.py) and the two `_sleep` branches in
test_settings.py pin it: the planner unloads after sign-off and at finish, and resident mode is the only opt-out.

### Step 5 (queue truthfulness) - done
Eight backlog rows in the store were stale against the docs (B7, B6d, B8 plus the queued B9-B13). Reconciled to
`cancelled` with "superseded - implemented directly by commit"; the inbox now shows one honest `needs you` (the RAG
case study) and the rest under RECENT. The inbox mislabel is fixed: queued+approved tasks are `QUEUED / RUNNING`,
never `RUNNING` alone (present.py and console.py agreed; two tests updated).
