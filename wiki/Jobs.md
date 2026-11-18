# Jobs: models write, Ariadne runs

## Why

On one machine, the model and the work it starts fight over the same GPU, RAM and time. The RAG build showed
what happens. The agent model (22 GB) was loaded while an ingest embedded thousands of chunks, so the two kept
evicting each other. Commands hit the 10-minute terminal limit, and one session pinned so much RAM that the PC
crashed.

The fix is to take execution away from the model. Models do the thinking and the writing, including all the code.
Ariadne does the running.

## How

```
model writes scripts/ingest.py ──► submit_job(command, why, after, expects, report, max_minutes)
model replies "JOB SUBMITTED: <id>" and its turn ends
worker: park the model's KV cache ─► unload every model ─► run the job (no terminal timeout)
worker: wake the same Hermes session with JOB_RESULT ─► model reads it and decides the next step
```

When the model is woken, it gets:
- the exit code and how long the job took;
- which expected files exist;
- the report file's content;
- the last lines of the log (`.ariadne/logs/jobs/<id>.log`);
- the note it left itself in `after`.

## What counts as a job

| Job | Not a job (stays in the terminal) |
|---|---|
| installs, downloads | read, grep, `git status` / `diff` |
| ingest, embedding, anything over many files | one quick test file |
| builds, evals, the full test suite, lint/type gates | `--help`, a one-file lint |

## Rules for a good job script (the `jobs` skill)

- A script in the workspace, not a one-liner. It takes `--sample N`.
- It can resume: it skips work that is already done, and saves progress in batches rather than one big
  transaction.
- It prints progress lines and writes a report file with real numbers. "Exit 0" alone is not evidence.
- Run the sample first, then the full run, with `max_minutes` set to about twice what the sample predicts.
- Never poll or sleep waiting for a job.

## Details

- MCP tools: `submit_job`, `list_jobs`, `job_result` (`ariadne/jobs_mcp.py`). They are in every flow.
- Each job has a hard stop (`max_minutes`, default 4 h, at most 8 h).
- `ariadne stop` cancels a task's pending and running jobs.
- Jobs run in the workspace folder with the worker's environment. Use the project's own venv for its tools.
