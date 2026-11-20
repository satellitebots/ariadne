# Status and roadmap

Mirrors `docs/BACKLOG.md`. An item is done only when the backlog says so.

## Done

| Step | What | Evidence |
|---|---|---|
| **1. Session-as-host** | `sessions` schema gains `model`, `workspace`, `brief`; `define_session`, `sessions_show`; `submit` joins by name and never spawns; `claim_next` by `created`. | GAP-ANALYSIS step 1; B22/B23 in BACKLOG |
| **2. MCP contract** | Disposable session to define the durable task interactively; step-wise reporting (callback/event channel, not polling); one task at a time. | B12.3, B12.8 |
| **3. GPU handoff pin** | `test_the_orchestrator_model_is_unloaded_before_execution` pins it: the planner unloads after sign-off and at finish; resident mode is the only opt-out. | test_discrepancies.py, test_settings.py |
| **4-slice-1. React UI** | React + Vite + TS rebuild of the console (shell, session rail, center stream, composer). | commit `f357980` |
| **5. Queue truthfulness** | Eight stale backlog rows reconciled to cancelled; inbox mislabel fixed (queued+approved = "QUEUED / RUNNING", never "RUNNING" alone). | commit `c6e856e` |

Additional done items from the backlog:

- **B12** (all sub-items): own runtime, the drill, MCP servers as runtime tools, skills, web search, context trimming + per-run log, todo/park/MCP markers, the flip (default runner is Hermes), chat on the runtime. Suite 281 passed.
- **B16**: Model index (`modelindex.py`), device scan, hardware-bounded shortlist, `--pulse`. 10 tests.
- **B17**: Hermes restored as the worker backend. `vendor/hermes` pinned submodule; `hermes_run` is the default runner; `ARIADNE_RUNTIME=own` selects the fallback. Suite 289 passed.
- **B18**: The overlay. `overlay.py`, `overlay.yaml`, `tools/sync_hermes.py`. 6 tests. Suite 295 passed.
- **B19**: Gates are proposed, never demanded. A task without gates starts and the planner proposes them.
- **B20**: Four retries, not ten rounds. `Flow.max_iterations` = 5.

## In progress

- **Step 6. Doc convergence and the wiki rewrite (B15).** The six stale pages (Concepts, Architecture, Flows-and-Skills, Models-and-Resources, Decisions, Status-and-Roadmap) rewritten to match the authority docs. Desktop.md deleted. This commit.

## Still open (from BACKLOG queue)

- **B21** (partly done): steer box in the console for a running task; `steer` on the chat's task card.
- **B22**: `ariadne sessions show NAME`; "New task in this session" from the console; session-level chat that survives tasks.
- **B23**: Full acceptance - `ariadne sessions` shows one session row with N tasks, not N one-task sessions.
- **B24**: Busy gate and interrupt-first steering. `service.busy()`, Stop parks, steering only for parked/stopped tasks.

## Deferred (needs a live model or the GPU)

- The first end-to-end run of any flow against a real model, and the RAG case-study task still sitting in the store.
- Load/stress behaviour of the watchdog under real VRAM pressure - thresholds get tuned then, not before.
- Retrieval-quality gates for B6d.
- A live CI provider (Jenkins/GitHub/GitLab) and a live embedding model.
- The LAN smoke test.

## Next (after B15)

- The first real overlay entry, when a module genuinely has to differ.
- Optionally, moving `hermes_run` from the `hermes` CLI to in-process `AIAgent`; the bootstrap and overlay are already in place.
- Keep this wiki honest as the code moves.
