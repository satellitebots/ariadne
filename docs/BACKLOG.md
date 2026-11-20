# Backlog

The queue. Each item is independently shippable, worked in order, and verified without loading a model unless the
item says otherwise. Done items move to the bottom with their commit. Nothing here is a live task in the store until
it is picked up.

Rules for every item: tests first where behaviour is involved; `upstream/` untouched; no cloud endpoints; the item's
own doc updated in the same commit.

## Queue

### B4 - `worker.py`: one session per task
Replace per-step `hermes chat -z` spawning with a single session that carries the plan, gates at the edge, and
`-r` resume on a failed gate. Per-step models become an explicit chain of sessions recorded in the plan. Deletes
`step_groups`, `agent_for` and the per-step retry machinery. *Model-free with a fake runner.*

### B5 - `store.py` extraction
Move the sqlite store out of the 1,482-line `orchestrator.py`; `service.py` becomes the only caller. Mechanical,
proved by the existing suite. *Model-free.*

### B6 - MCP servers: `data`, `office`, `ci`, `rag`
Declare each in `flows/mcp_servers.yaml` as it is built; names are already approved in `flows/tools.yaml`.
- B6a `data`: csv/parquet/sqlite profile, query, transform.
- B6b `office`: docx and xlsx read/write.
- B6c `ci`: Jenkins, GitHub Actions, GitLab - trigger, status, logs.
- B6d `rag`: ingest, chunk, embed, vector store, retrieval eval with a numeric gate.
*Model-free except embedding calls in B6d.*

### B7 - `diagram`: draw.io / diagrams.net export
Mermaid stays primary; add an open-source Visio-class path (import/export `.drawio`, SVG/PNG render) for design p80.

### B8 - Content flow: reference-based generation
A source-pack step (fetch or ingest references), claims carrying citations, a fact-check pass, and the source list as
part of the report. House style saved as a skill so the next run starts with it.

### B9 - `ariadne/server` + `ariadne/ui`
FastAPI on loopback (or `ARIADNE_BIND` for the LAN): the verbs from `service.py`, the views from `present.py`, SSE
for live activity. Static ES-module SPA, no bundler, no Node. Sessions-first console: Needs-you strip, sessions,
timeline + backbrief, decision panel. *Model-free.*

### B10 - Our own chat
Session-bound conversation whose tools are the service verbs plus read-only lookups. No files, terminal, code or
browser - it cannot do the work by construction.

### B11 - Schedules from sessions
`service.schedule_create(session, cron, overrides)`; a schedule inherits the session's flow, model, workspace and
gates; the serve loop submits due occurrences with `source="schedule"` into the same session. Creating a schedule
goes through sign-off once - that is the standing authorisation.

### B12 - Runtime fork strip
Vendor the pin into `ariadne/runtime/`, then delete one subsystem per commit with the suite green after each:
desktop app, messaging, connectors/sign-in, cloud providers, model catalog fetch, telemetry, update checks,
computer-use. Log every removal in `docs/FORK.md`.

### B13 - Install and doctor for the new dependency set
Drop Node (it was only for the Electron build); `doctor` reports Python, Ollama or the active server, git, uv, GPU,
and the tools the approved flows name.

### B14 - Retire `ariadne_gate`
Once B10 exists, the chat has no doing-tools to refuse. Delete the plugin and its tests; keep the rule in docs.

### B15 - Wiki rewrite
The six stale pages (Flows-and-Skills, Models-and-Resources, Concepts, Architecture, Decisions, Status-and-Roadmap),
then delete `Desktop.md`, then publish with `tools/publish_wiki.py`.

## Explicitly deferred (needs a live model or the GPU)

- The first end-to-end run of any flow, and the RAG case-study task still sitting `executing` in the store.
- Load/stress behaviour of the watchdog under real VRAM pressure - the thresholds get tuned then, not before.
- Retrieval-quality gates for B6d.

## Done

- Inference follows the active server (`serving.endpoint()`; llm, KV cache, image, jobs, flow homes) - this commit
- Watchdog wired into the worker (`_watchdog` in `orchestrator.serve`, real unload/kill/flag callbacks,
  act-once escalation) - `41784f9`
- `timed_out` and the task wall-clock (`orchestrator.py`, `present.py`, flows) - `c334e8e`

- Watchdog: escalation, sampling, jsonl trail (`ariadne/watchdog.py`) - this commit

- Model server abstraction (`ariadne/serving.py`, `serving/servers.yaml`) - `de289ef`
- Approved tool set widened to p90 + coverage/runtime contract - `c7a2425`
- Backend congregation: `service.py`, `present.py`, `protocol.py`, `render.py`; MCP lockdown - `f7b6353`
- Local-only provider lock (`ariadne/local_only.py`) - `f7b6353`
- Frontend pivot: desktop plugin retired - `f7b6353`, `ef04a14`
