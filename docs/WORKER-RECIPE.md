# The worker recipe: what a local worker gets wrong, and what the system does about it

Written from the 24-25 November runs (googl-daily v1-v6, the terminal and UI case studies) so the next task does
not have to rediscover any of it. The GOOGL task was the probe, not the subject: every entry below is stated for any
task, with the GOOGL event that showed it. Read this before defining a task, and before changing a flow template.

The worker these notes describe: a ~35B mixture-of-experts model (~3B active), 4-bit, 64K context, on an 8 GB GPU,
driving Hermes one step at a time. A bigger model moves the thresholds, not the classes.

## 1. What the worker cannot be trusted to do

| # | Failure class | Seen as | The rule that removes it | Where it lives |
|---|---|---|---|---|
| W1 | It does not know when or where it is | v1 reported Sep-Dec 2025 as "the last 3 months"; jobs failed on `python3` and `cd /c/...` | Every prompt carries TODAY, the task's time zone, the OS, the shell jobs run in and its path style | `engine.STEP_PROMPT`, `PLATFORM` (built in) |
| W2 | It computes numbers in prose, and gets them wrong | The 1-month change came out two ways; the 3-month low was a close, not a low | **Facts first**: a script writes every number to a facts file with a fixed schema; prose copies them; a check compares | skill `facts-first`; check `facts_in_report.py` |
| W3 | It fills ambiguous definitions its own way | "pct" came back as a fraction; "1 month" as 20 calendar days vs 21 trading rows | The definition states each measure as a formula with units and window, and a check recomputes it from raw data | task definition; check recomputes |
| W4 | Verification drifts into redoing the work | Verify re-researched the web, ran out of time, and rewrote the data it was meant to check | Verify is local and read-only on the sources of truth: deterministic checks first, a reviewer last, never edit `data/` | skill `verify-locally`; template step 5 |
| W5 | Long, open-ended steps degenerate | 266 identical `ls` calls with empty replies, ignoring 60 warnings, at ~44K tokens | Small steps (one deliverable, ~30 tool calls), scripts instead of interactive poking, a fresh session per attempt; loops are reported live | skill `stay-unstuck`; `Progress` looping events |
| W6 | It attributes sources loosely | A blockonomi.com link credited to "BNN Bloomberg" | A sources ledger with URL, publisher and date per line; a check that the publisher matches the URL's site and the date is inside the window | check `sources_ledger.py` |
| W7 | "Recent" means whatever it found | News items weeks old in a "last 2 weeks" answer | A recency window as a parameter, dates on every source, the check enforces the window | `sources_ledger.py --within-days` |
| W8 | It trusts files it did not make | Stale v1 outputs made v2 fight its own leftovers | The engine archives a run's outputs to `.history/` at start; steps read only what earlier steps of *this* run left | engine (built in) |
| W9 | After writing a script it keeps checking instead of running it | `ls` the script, delete `.venv`, `ls` again, never `submit_job` | Write it, submit it, stop. Same call twice with the same result means change approach | skills `jobs`, `stay-unstuck` |
| W10 | A reviewer is right more often than the writer | The final reviewer caught the wrong 3-month low that four steps missed | Keep a read-only reviewer as the last gate on every task that makes claims; give it the claims to check | flow template gates |

## 2. What the harness must guarantee (each was a real bug, now fixed)

- **One owner of the GPU, really.** Hermes runs every session through a gateway in the worker home. A park or a
  cancel that only stops the CLI leaves the turn running (a "parked" run at 98% GPU; a cancelled run revived by the
  gateway's auto-continue). Park, ask and cancel stop the gateway; its auto-continue is off.
- **A resumed session gets the same tools, skills and model.** Without them a resumed worker asked for its skills
  forever.
- **Nothing rewrites config it does not change.** llama-swap watches its config; rewriting the same text every 2 s
  reloaded it 1,590 times and failed every request in flight.
- **No clocks, no caps, no silent kills.** Runs end done, failed or cancelled. Progress is pushed (tool calls, model
  calls, job output, quiet and looping notes); whoever decides reads `progress` first.
- **No permission refusals.** Hermes's guards are off; `permissions.yaml` is the only policy, empty by default.
- **A single step never carries the whole task.** A planning step writes `## Steps`; `each:` runs one fresh step
  per item. One "do the task" step wrote a whole study guide in one 8-minute call: unchecked, off-syllabus in places,
  with a convention backwards (case study 26 Nov).
- **A reviewer's FAIL is not retried.** It goes to the person; only facts (scripts, missing outputs) retry, once.
- **A cancel is immediate**, and a run whose worker died while you cancelled it ends cancelled, not stuck.
- **`now` runs once.** The scheduler never starts `now` or `manual` tasks.
- **Steering notes hold for the rest of the run**, and the orchestrator proposes a note instead of acting on a run
  it was only asked about.

## 3. The inputs that were given, and what each calibrated

Kept as a log so a future change can be traced to the evidence. "Generalised as" is the rule in section 1.

| Input given | Why | Generalised as |
|---|---|---|
| TODAY and time zone in step, review and orchestrator prompts | v1 answered about the wrong months | W1 |
| Windows notes, Git Bash for jobs, forward slashes | jobs failed in cmd.exe | W1 |
| Archive outputs at run start | stale files, overwrite refusals | W8 |
| `compress_at` 30K to 44K | compression ran every turn (~6 min each) | W5: context is the scarce resource |
| Fixed keys for `indicators.json`; report copies them; gate compares | numbers drifted between files | W2 |
| `pct` in percent, with formula; gate recomputes | fraction vs percent | W3 |
| 1 month = 21 trading rows, 3 months = 63 | two definitions in one report | W3 |
| Verify: no web, never edit `data/`, file and terminal only | verify redid the work and corrupted it | W4 |
| Gate scripts print what is wrong, avoid `%` (cmd.exe), never traceback | unreadable or mangled gate failures | Gates are files under `flows/common/checks/` |
| "Submit the job as soon as the script exists" note | loop on `ls` | W9 |
| "Last 2 weeks, primary sources, name the real publisher" note | old news, wrong attribution | W6, W7 |
| 3-month high/low produced by the data step | the report computed a low from closes | W2 |

## 4. How to use this when defining a task (the orchestrator follows this)

1. **Does the answer contain numbers?** Add a facts step before writing: a script writes `data/facts.json` (every
   number the answer will use: value, unit, as_of, source, and the formula when derived). Gate it with
   `python {checks}/facts_in_report.py REPORT.md data/facts.json` after the writing step.
2. **Is any measure ambiguous?** Write its formula, units and window into the step instruction. If raw data is
   available, add a gate that recomputes it.
3. **Does it cite sources?** Ledger format `- <url> | <publisher> | <what it supports> | <YYYY-MM-DD>` and gate with
   `python {checks}/sources_ledger.py SOURCES.md --min 3 [--within-days N]`.
4. **Keep steps small**: one deliverable, roughly thirty tool calls. Split any step that both researches and writes.
   Anything with parts (sections, changes, views) is planned as a `## Steps` list and done with `each:`.
5. **Verify last, locally**: deterministic checks as run gates (`plan_steps`, `verify_result`, `piece_check`,
   `sources_ledger`, `facts_in_report`), then at most one review gate that names the claims to check.
6. **Heavy work is a job** (installs, downloads, data pulls, builds, test suites).

## 5. Open, known limits

- Turn latency: a chat turn costs one to three minutes on this machine; time-critical actions are slash commands.
- The model can still loop; looping is reported, not acted on. A fresh session (cancel and rerun the step) clears
  it; resuming the same session usually does not.
- A reviewer can be wrong too. Run gates first so the reviewer only judges what a script cannot; its FAIL goes to
  the person, never back into the work.
- A plan is only as good as the planner: `each:` makes every item its own step, but a missing item stays missing.
  Give the planning step the source of truth for coverage (a syllabus, an outline, a spec) as an input.
