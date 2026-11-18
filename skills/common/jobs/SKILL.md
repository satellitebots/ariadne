---
name: jobs
description: Hand heavy work (installs, ingest, embedding, builds, evals, full test suites, downloads) to Ariadne as a job instead of running it in the terminal. Use whenever a command could take more than a minute or load the machine.
---

# Jobs: you write it, Ariadne runs it

You share one machine with the work you start. While you are loaded, a heavy command fights you for GPU, RAM
and time, and the terminal times out. So you do not run heavy work. You write it, and Ariadne runs it with
you unloaded, then wakes you in this same conversation with the result.

## When it is a job

A job: installs (`pip install -e .[dev]`), downloads, ingest or embedding, builds, evals, the full test suite,
anything that loops over many files or calls a model or API many times, anything you would put in the background.

Not a job: read or search files, `git status`/`diff`, a single quick test file, `--help`, a one-file lint. Run
those in the terminal.

## How

1. Write a script in the workspace (`scripts/<name>.py`), not a one-liner. It must:
   - take `--sample N` (do a few items) and run the full set without it;
   - be resumable: skip work that is already done (check the output before redoing it);
   - commit progress in small batches (one transaction per batch, not one for the whole run);
   - print progress lines (`[120/1960] file.md`) and write a report file with real numbers
     (`reports/<name>.json`: counts, failures, seconds).
2. `submit_job(command="python scripts/<name>.py --sample 5", why="...", after="...", expects=[...],
   report="reports/<name>.json", max_minutes=...)`.
   `after` is your note to yourself: what to check and what to do next. You will read it when you wake.
3. Reply exactly `JOB SUBMITTED: <id>` and nothing else. Your turn is over.
4. You wake with exit code, duration, the report, which expected files exist, and the end of the log.
   - Sample passed: submit the full run (same script, no `--sample`), with a `max_minutes` from the sample timing.
   - Failed: read the log tail, fix the script, resubmit. It resumes; never delete finished work to start over.
   - Done: check the report numbers against what the task needs before you call the step done.

## Rules

- One job per heavy thing; several small heavy things can be one script.
- Never poll or `sleep` waiting for a job. Never run the same command in the terminal "to see".
- Name every output in `expects`, and always write a report file. "exit 0" alone is not evidence.
- Set `max_minutes` to about 2x the time the sample predicts.
- Quality gates (ruff, mypy, full pytest) are jobs too: `python -m pytest -q > reports/pytest.txt`.
