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

**Left, in order (each its own commit).** The rule that was missing the first time: an item is done only when a test
exercises it with `HERMES_EXE` pointed at a path that does not exist. Sizes and the full argument are in
`docs/GAP-ANALYSIS.md`.

- **B12.7 flip the default and delete Hermes.** Make the runtime the default, delete `hermes_run`, `_clean_output`,
  `_kill_tree`, `_turn_end_reason`, `_latest_session`, `stop_gateway` (~134 lines, 36 references) and the `upstream/`
  submodule; update `docs/FORK.md` and `docs/DESIGN-RESET.md`.
  *Done when:* the whole suite passes with no `upstream/` directory and no `hermes` binary, including the drill.
  Net -134 lines.
- **B12.8 the chat on the runtime.** `ariadne chat` still launches `hermes chat`; it moves onto `runtime.run` with the
  same restricted toolset, then B15 writes the wiki about what actually ships.
  *Done when:* chat answers with `upstream/` deleted.
  ~80 lines.

### B15 - Wiki rewrite
The six stale pages (Flows-and-Skills, Models-and-Resources, Concepts, Architecture, Decisions, Status-and-Roadmap),
then delete `Desktop.md`, then publish with `tools/publish_wiki.py`.

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
