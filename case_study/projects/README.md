# Case-study projects

What the local models actually produced, checked in so you can read the code, not just the write-ups. Each folder
is a snapshot of the workspace a case study ran in (`.snapshot.json` says which commit), taken with
`python -m ariadne casestudy export <workspace> <name>`. Only what the workspace's git tracked is included; corpora,
indexes and scratch files stay out.

| Project | Case study | State |
|---|---|---|
| [todo-app](todo-app/) | [TODO_case_study.md](../TODO_case_study.md) | Done: all gates passed, 18 tests |
| [rag-design](rag-design/) | [RAG_case_study.md](../RAG_case_study.md) | Done: DESIGN.md + four rendered diagrams (~85%) |
| [rag-build](rag-build/) | [RAG_case_study.md](../RAG_case_study.md) | In progress: library + 24 tests; ingest, README and eval not done |

Run a project's tests from inside it, e.g. `cd todo-app && python -m pytest -q`.
