---
name: long-jobs
description: How to run work that takes minutes or hours (ingest, embedding, installs, builds, big test suites, downloads) without hitting the terminal timeout - background it, chunk it, make it resumable, record progress.
---
# Long jobs

The terminal tool stops a foreground command after its timeout (at most 600 s). A run also has a time budget and a
turn limit, and anything still running when the run ends is stopped. So never bet on one long command finishing.
(RAG build: a full ingest run in the foreground died at 600 s, twice, and the next attempt started it from zero.)

## Before you run it: measure
1. Run it on a small sample first (`--limit 20`, one folder, one file). Check the result is right end to end.
2. Time the sample and estimate the full run. Say the estimate in your next message.
3. Under 2 minutes: run it in the foreground with `timeout` set generously.
   Longer: use the background pattern below.

## Background pattern
- Start it with `terminal(command=..., background=true, notify=true)` and keep the `session_id`.
- Make the command print progress lines (`done 120/3400 docs`) and write them to a log file in the workspace.
- Wait with `process_manage(action="wait", session_id=..., timeout=300)`, then `poll` for new output. Repeat while
  it makes progress. Between waits, do other plan steps that do not depend on it (README sections, tests).
- If it fails, read the log, fix the cause, and resume it - do not start over.

## Make the job resumable (write the code this way)
- Process in batches (e.g. 50 documents) and commit each batch (database transaction, or append to a file).
- Skip work already done: an `--resume` flag, or check what is already in the index before processing.
- Keep a progress record the next run can read: `.progress.json` (or the DB itself) with counts and the last item.
- Add `--limit N` for samples. Idempotent: running it twice gives the same result.
- At the end write the real numbers to a file (e.g. `ingest_report.json`: documents, chunks, seconds). README text
  and gate evidence quote that file, never a guess.

## If the run might end first
Your run can end (time budget, turn limit) while the job is still going. That is fine when the job is resumable:
leave it a clear note in your report ("ingest at 1200/3400, resume with `python -m rag ingest --resume`") and the
next attempt continues from the progress record.

## When planning
Give long work its own step, planned as: sample run -> estimate -> background run with progress -> verify counts.
If the estimate is over ~30 minutes, split it into steps by part (folders, batches of files) so each step finishes
with its own evidence.
