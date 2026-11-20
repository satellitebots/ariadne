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

**Left, in order (each its own commit).** The rule that was missing the first time: an item is done only when a test
exercises it with `HERMES_EXE` pointed at a path that does not exist. Sizes and the full argument are in
`docs/GAP-ANALYSIS.md`.

- **B12.5 web search.** `web_search` over `ddgs` (installed); `web_fetch` already exists in `web_mcp` and arrives with
  B12.3. Without this a runtime plan cannot research, which is half of what the plan prompts ask for.
  *Done when:* a run searches, gets results, and fetches one of them.
  ~40 lines + test.
- **B12.6 parity hooks.** Park (`StepBoundary` + `park.requested()`), KV registration, the jobs wake-up loop
  (`JOB SUBMITTED` -> unload -> run -> resume the same session), a per-run `.log` artifact like `hermes_run` writes, a
  `todo` tool, and context trimming (the message list grows unbounded today).
  *Done when:* a task pauses and resumes on the runtime, a submitted job runs with the model unloaded, and a
  long run stays inside the context window.
  ~270 lines + tests.
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
