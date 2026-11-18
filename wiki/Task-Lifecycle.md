# Task lifecycle

![Task lifecycle](../docs/img/task-lifecycle.png)

| # | Phase | Who | What happens |
|---|---|---|---|
| 1 | Brief | You | Task text, workspace, check gates. With no gates, the task waits in `awaiting_gates` and asks for them. |
| 2 | Route | Router model | Picks the flow, unless you named one. |
| 3 | Plan | Flow's planner | Read-only tools only (enforced by the `ariadne_phase` plugin). Reads the workspace, searches the web and docs, recalls memory. |
| 4 | Backbrief | Planner → you | Mission, steps, a model per step, a gate→step map, risks. Status `awaiting_signoff`. |
| 5 | Sign-off | You | Approve (optionally overriding a step's model), revise with feedback, or cancel. Approving locks the plan. |
| 6 | Execute | Each step's model | Step groups run in order. A checkpoint between groups writes a handoff brief. Heavy work goes out as [jobs](Jobs.md). A needed login [pauses the task](Web-and-Browser.md). |
| 7 | QA | Gate commands + reviewer | Command gates run; review gates are judged by a separate read-only reviewer run. Failures go back to step 6 with the reasons. |
| 8 | Report | Worker | What changed and how it was verified. Status `done`. |

## Statuses

`planning` → `awaiting_gates` / `awaiting_signoff` → `executing` → `done`

Off the main path:
- `needs_attention`: the task needs you. This happens when you stopped Ariadne, a model is missing, or the QA loop
  ran out of rounds.
- `failed`: an error the worker could not recover from.
- `cancelled`: you cancelled it.

Approving a `needs_attention` task continues it, keeping the work so far.

## Limits that end a loop

| Limit | Value | When it is hit |
|---|---|---|
| QA rounds | 10 | `needs_attention` with the failing gates |
| No progress | 2 rounds with no fewer failing gates | Stops early |
| Turns per run | coding: plan 20, execute 80 | The gates decide whether it is done |
| Run budget | coding: plan 45 min, execute 60 min | Same: the gates decide |
| Job cycles per run | 40 | Stops submitting jobs |

Running out of turns or time is not a failure: what the model wrote stays, and the gates decide. This was learned
on RAG v1, where a 40-turn limit marked good work as failed.
