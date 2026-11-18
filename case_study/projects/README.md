# Case-study projects

What the local models actually produced, checked in so you can read the code, not just the write-ups. Each folder
is a snapshot of the workspace a case study ran in (`.snapshot.json` says which commit), taken with
`python -m ariadne casestudy export <workspace> <name>`.

A snapshot includes what the workspace's git tracks, plus any uncommitted edits the model left in those files (a run
that stopped mid-step). Corpora, indexes and scratch scripts stay out.

| Project | Case study | State |
|---|---|---|
| [todo-app](todo-app/) | [TODO_case_study.md](../TODO_case_study.md) | Done: all gates passed, 18 tests |
| [rag-design](rag-design/) | [RAG_case_study.md](../RAG_case_study.md) | Done: DESIGN.md + four rendered diagrams (~85%) |
| [rag-build](rag-build/) | [RAG_case_study.md](../RAG_case_study.md) | Stalled: library + 24 tests at commit 9c25af7, plus uncommitted edits to `commands.py` and `generator.py`; ingest, README and eval not done |

Run a project's tests from inside it, e.g. `cd todo-app && python -m pytest -q`.
