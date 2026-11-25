# Task lifecycle

| # | Stage | Who | What happens |
|---|---|---|---|
| 1 | Draft | You + orchestrator | `draft` opens the flow's template; what you typed answers its first question. The orchestrator asks for the rest (at most two questions at a time) and writes the full definition with `draft_update`. |
| 2 | Sign | You | Only a draft with no problems signs. It becomes version N of the task; a `now` trigger queues a run at once. |
| 3 | Queue | Scheduler | `run`, a due trigger, or `rerun` queues a run. Runs are taken oldest first. |
| 4 | Machine | Broker | The run waits for the lease; the console and `machine` say who holds it. |
| 5 | Steps | Workers | Each step: a fresh Hermes run with the step's tools, the files earlier steps left, any steering notes. Heavy work goes out as a job. |
| 6 | Check | Command or reviewer | The step's outputs must exist and its gate must pass. A failure is retried with the reasons (`retries`, default 1), then the run needs you. |
| 7 | Gates | Command or reviewer | The task gates, after the last step. |
| 8 | End | Engine | done, failed, timed out (`budget_s`), cancelled, or needs you, with every step's report kept. |

## Between steps

- **Boundary yield:** if someone waits for the machine, the run gives it up before its next step and queues again.
- **Park:** stops the step at its next boundary, saves its cache, frees the machine. Talk to the orchestrator, `steer`,
  then `resume`: the same step continues with your notes.
- **Cancel:** a queued run ends now; a running one at its next boundary.
- **Off-plan:** a worker that finds the definition wrong says so (`OFF-PLAN:`), and the run needs you: edit the task,
  sign the next version, run again.
