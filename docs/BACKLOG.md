# Backlog

The queue. Each item is independently shippable, worked in order, and verified without loading a model unless the
item says otherwise. Done items move to the bottom with their commit. Nothing here is a live task in the store until
it is picked up.

Rules for every item: tests first where behaviour is involved; `upstream/` untouched; no cloud endpoints; the item's
own doc updated in the same commit.

## Queue

### B12 - Runtime fork strip
Vendor the pin into `ariadne/runtime/`, then delete one subsystem per commit with the suite green after each:
desktop app, messaging, connectors/sign-in, cloud providers, model catalog fetch, telemetry, update checks,
computer-use. Log every removal in `docs/FORK.md`.

### B13 - Install and doctor for the new dependency set
Drop Node (it was only for the Electron build); `doctor` reports Python, Ollama or the active server, git, uv, GPU,
and the tools the approved flows name.

### B15 - Wiki rewrite
The six stale pages (Flows-and-Skills, Models-and-Resources, Concepts, Architecture, Decisions, Status-and-Roadmap),
then delete `Desktop.md`, then publish with `tools/publish_wiki.py`.

## Explicitly deferred (needs a live model or the GPU)

- The first end-to-end run of any flow, and the RAG case-study task still sitting `executing` in the store.
- Load/stress behaviour of the watchdog under real VRAM pressure - the thresholds get tuned then, not before.
- Retrieval-quality gates for B6d.

## Done

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
