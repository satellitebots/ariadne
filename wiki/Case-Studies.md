# Case studies

Real runs on the reference machine. Everything is in [`case_study/`](../case_study/README.md): the write-ups, the
briefs, the raw run notes, screenshots, and the code the models produced (`case_study/projects/`).
Snapshots are taken with `python -m ariadne casestudy export <workspace> <name>`.

| Case study | Flow | Outcome | Write-up | Project |
|---|---|---|---|---|
| Todo app | coding | Done: all 5 gates, 18 tests. Took four runs to get there. | [TODO_case_study.md](../case_study/TODO_case_study.md) | `projects/todo-app` |
| Company RAG: design | design | Done, about 85% against an 80% bar | [RAG_case_study.md](../case_study/RAG_case_study.md) | `projects/rag-design` |
| Company RAG: build v1 | coding | Stalled: the library and 24 tests are done; ingest, README and eval are not | same | `projects/rag-build` |
| Stock analytics package | coding | Planned: the first run on jobs and coding standards | (to come) | (to come) |

## What each one changed in Ariadne

| Lesson | From | Became |
|---|---|---|
| A planner that picks a different model for every step loses context at every swap | Todo, RAG | `planning-lessons`: one model per codebase; plans favour MoE models |
| Running out of turns is not failing | RAG build | Out of turns or time goes to the gates; coding gets 80 turns |
| An embedding model and an agent model on one GPU thrash | RAG build | Embeddings moved to a persistent CPU group |
| Long commands in the model's terminal time out and hold the machine | RAG build | [Jobs](Jobs.md) |
| `max` pinning 90% of RAM crashed the PC under a CPU ingest | RAG build | RAM cap 80%; limits measured at boot |
| Processes started from a remote session died with it | RAG build | Detached worker and model server; stop only on purpose |
| Diagram renders with relative paths landed outside the workspace | RAG design | Absolute paths required; `design-lessons` |
| Models write code from memory | RAG build | `coding-standards` + `web_fetch` of official docs |

## Next: stock analytics

The stock analytics package is an independent Python package that pulls Yahoo Finance data and computes analytics
(returns, volatility, drawdowns, simple indicators). It is built through Ariadne end to end:
- the data pulls, test suite and lint/type gates run as jobs;
- the code is written to the coding standards;
- the skills are calibrated from what the run shows.

It does analytics only, not financial advice.
