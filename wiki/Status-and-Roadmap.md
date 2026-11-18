# Status and roadmap

*As of 18 Nov 2026.*

## Where things stand

| Area | State |
|---|---|
| Coding flow | Beta. Validated on the todo app; RAG build partly done |
| Design flow | Used for the RAG design (about 85%); still marked experimental |
| Writing, content flows | Shipped, not validated |
| Jobs | Built and tested (unit and worker-loop tests); not yet used on a real run |
| Web search, `web_fetch`, browser, debug-mode logins | Built and tested; not yet used on a real run |
| Coding standards skill | Written; to be calibrated on the stocks run |
| Desktop | Changes in; not being run until the end |
| Worker and models | Down since the 18 Nov crash; nothing starts on its own |
| RAG build task `t1117-202509-ce9e` | Stale `executing`. Library + 24 tests committed; ingest never committed (killed in the crash); `_debug_*.py` left behind |

## Next

1. **Stocks case study.** Hand back the stale RAG task (`ariadne stop`), start the worker and models (pick `max`
   or `shared`), and submit the stock analytics package with gates. Watch the first jobs.
2. **Calibrate skills from that run.** Update `jobs`, `coding-standards` and `planning-lessons` with what the
   models actually did.
3. **RAG build.** Redo the ingest and eval as jobs: clean up the debug scripts, then resume or resubmit.
4. **Validate** the writing and content flows, then the desktop.

## Later

All the parked ideas are in [TODO.md](../TODO.md): chat hijack, the two home servers, compression and
instruction-decay telemetry, default quality gates, Slack, and others.
