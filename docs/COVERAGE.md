# Flow coverage and the runtime contract

Two things this document settles: what each flow must be able to actually do (p90, not p50), and how the runtime
behaves when one model has the machine — callbacks, timeouts, and a watchdog that is a script, never a model.

Coverage rule: anything a flow may need is in `flows/tools.yaml`. If it is not installed, the backbrief names it
under `TO INSTALL AFTER SIGN-OFF` with the exact command, and approving the plan authorises the install. A flow that
cannot reach its p90 with the approved set is a bug in the set, not a limitation to accept.

## Coding

- **p50**: read and edit files, terminal, git, run the tests, VS Code.
- **p80**: docker build/run/compose, CI (Jenkins, GitHub Actions, GitLab) trigger + status + logs, `gh` for PRs and
  issues, k8s manifests, jq/rg/sqlite3, database migrations, a browser check against a local UI.
- **p90**: **RAG builds** — ingest, chunk, embed, vector store, retrieval eval with a numeric gate; helm/kubectl
  against a cluster on the LAN; multi-service compose; profiling; media pipelines (ffmpeg).
- Tools: `vscode`, `git`, `browser`, `jobs`, `memory` + `ci`, `data`, `rag` (MCP) + docker, kubectl, helm, gh, jq,
  rg, sqlite3, ffmpeg (system).
- Gates that belong here: tests, lint, build, and for RAG a retrieval metric (`recall@5 >= 0.8`) rather than "it runs".

## Design

- **p50**: markdown plus Mermaid diagrams.
- **p80**: diagram sets (C4 / architecture / sequence / ER), SVG+PNG rendering, an open-source Visio-class editor
  path (draw.io / diagrams.net import-export), and a review packet exported to docx or pdf.
- **p90**: system and RAG architecture with trade-off matrices, data-flow plus deployment views, ADRs, and a
  rendered pack that can be handed to someone who was not in the room.
- Tools: `text`, `diagram`, `export`, `office`, `web` (to read references and prior art).

## Investigation

- **p50**: web search and fetch, read the repo.
- **p80**: the debug browser (chrome-devtools MCP) for JS-heavy or authenticated sources, csv/xlsx ingestion, sqlite
  queries, docx/pdf reading, and a citation trail.
- **p90**: multi-source triangulation, dataset profiling, reproducible evidence (each claim tied to a source and a
  retrieval step), and an exported report with citations.
- Tools: `web`, `browser`, `data`, `office`, `export`, `memory`.

## Content

- **p50**: write from a brief.
- **p80**: **reference-based generation** — fetch or ingest source material, extract claims with citations, match a
  house style, produce markdown/docx, generate and place images (sd-turbo / Z-Image-Turbo).
- **p90**: long-form from a source pack with a fact-check pass, illustrated, exported to docx/pdf, and the house
  style saved as a skill so the next run starts with it.
- Tools: `text`, `web`, `office`, `image`, `export`, `diagram`, `memory`.
- Rule: a claim taken from a reference carries its citation, and the source list is part of the report — not a
  footnote the model may skip.

## The runtime contract

One model at a time, and **callback rather than waiting**.

1. **Every task ends in a callback.** Terminal states: `done`, `failed`, `cancelled`, `rejected`,
   `needs_attention`, `timed_out`. A caller either waits with a bound (`wait_task`, max 280 s) or is notified by the
   store; nothing may block indefinitely, and no caller may have to poll to learn the outcome.
2. **Three timeout levels.** Phase (`run_budget` for plan and execute), turns (`max_iterations`), and a task
   wall-clock. Any of them ends the task in a terminal state with the reason recorded. Out of time or turns is *not*
   failure: what was written stays, and the gates decide.
3. **A watchdog that is a script.** `ariadne/watchdog.py` samples VRAM, RAM, CPU and the model server's health every
   few seconds while a model is loaded, against fixed thresholds (free RAM, free VRAM, health-check latency).
   Escalation is deterministic and logged: **warn → unload the model → kill the server → mark the task
   `needs_attention`** with the readings that caused it. If the machine looks like it is about to die, the model
   dies first. Every sample and every kill goes to `.ariadne/watchdog.jsonl`, so a crash is explainable afterwards.
4. **Heavy work goes through jobs.** Installs, ingest, embeddings, builds, evals and downloads are submitted as jobs:
   the model is unloaded, the job runs, and the model is woken with the result. That is the existing callback
   machinery, and the watchdog supervises jobs as well as runs.
5. **Determinism rules.** No model in the control path — routing, retries, gates and kills are code. Every state
   transition is a store write plus an event. Retries are bounded and counted. Same inputs, same path. A babysitter
   is never another model, because a model is the thing that can hang.

## Approved but not built

| Gap | Where it lands |
|---|---|
| `ci`, `data`, `office`, `rag` MCP servers | names approved in `flows/tools.yaml`; declare them in `flows/mcp_servers.yaml` as they are built |
| draw.io / diagrams.net export | `diagram` server |
| reference ingest for content | `content` flow: a source pack step plus citations in the report |

Built since this list was written: the task wall-clock and `timed_out` (B1), and the watchdog wired into the worker
(B2: `_watchdog` in `orchestrator.serve`; unload via llama-swap `/unload`, kill via `serve.stop`, flag = every
`planning`/`executing` task goes `needs_attention` with the readings). Threshold tuning still waits for a real load.
