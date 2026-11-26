# Case study: the terminal chat, 25 November 2026

**What was tested.** `python -m ariadne chat` in a terminal, driving a real run of `googl-daily` (v5, five steps on
qwen3.6-35b-a3b, 8 GB GPU) end to end: ask what is running, park, talk it over, steer, resume, cancel, start again.
Every Hermes restriction was already lifted (permissions.yaml: allow everything).

**Verdict.** The chat now works as the front it is meant to be, but only after six fixes; four of them were real
bugs that every front shared. All six are in `main` with tests (235 passing).

## What happened, and what changed

| # | Seen in the terminal | Cause | Fix (commit) |
|---|---|---|---|
| 1 | "what is running?" printed nothing for 4.5 min, then a correct answer | The orchestrator waited silently for the worker's step to end, then swapped models both ways (27B in, 35B-A3B back) | The chat says when a message must wait and how to park; outside a draft the orchestrator uses the model already loaded or parked, so no swap (f6b3242, c0b92a7) |
| 2 | "park the googl run" queued behind the very step it meant to stop | Parking went through the model, which needs the machine | `/park /resume /steer /approve /reject /cancel /status` act at once, without the model. Parked in 5 s (f6b3242) |
| 3 | Asked "what should I tell it?", the orchestrator steered **and resumed** the run itself | Its instructions allowed acting "when asked"; it read advice as an order | It acts on a run only when told to; otherwise it proposes the exact note and asks (c0b92a7) |
| 4 | A note meant for step 3 was consumed by step 2's resume | Notes were delivered once, to whichever step came next | A note holds for the rest of the run; every later step gets all of them (c0b92a7) |
| 5 | After resume, the worker called `skill_view` on the same five skills for 15 minutes | `hermes --resume` started without `-t/-s/-m`, so every skill lookup failed | A resume gets the step's tools, skills and model; a repeating worker is reported as **looping** (never stopped) (935820b) |
| 6 | "start googl-daily again" died with HTTP 500 and the chat exited with a traceback | The idle daemon rewrote the model-server config every 2 s; llama-swap reloaded 1,590 times and failed requests in flight | The config is written only on a real change (0 reloads since); the chat reports errors and carries on (1d526ab) |

Alongside these, prompted by the person mid-study: no clocks and no turn caps anywhere (a run ends done, failed or
cancelled; killing is deliberate), and progress is pushed live: every tool call, model call and job output becomes a
run event, `progress` answers "is it still moving?" on every front, and the chat prints the orchestrator's waits,
model calls and tool calls as they happen (f6b3242).

## The session after the fixes

```
you> /status
worker r1125-185912-e6aa holds the machine (qwen3.6-35b-a3b, 180 s)
  r1125-185912-e6aa  running  googl-daily  step 2/5
      last: step 1: model call 4: 13,358 tokens in, 218 out, 9 s (23 s ago; 4 tool calls, 4 model calls)
you> /park
r1125-185912-e6aa (googl-daily, running): parking: it stops at its next tool call and gives the machine back
you> start googl-daily again now
   . model call 1: 99 s, 1 tool call(s)
   . called tasks {}
   . model call 2: 24 s, 1 tool call(s)
   . called run {"task": "googl-daily"}
   . model call 3: 35 s, 0 tool call(s)
ariadne> Started: run r1125-192634-941c of googl-daily (version 5) is queued, 5 steps.
you> /steer In step 3 (Gather evidence) use news from the last 2 weeks only, from primary sources first ...
r1125-192634-941c (googl-daily, running): noted: it reads this at its next boundary
```

## Still open

- A chat turn costs 1-3 minutes on this machine (the first call after a load is the slowest). The slash commands
  cover the time-critical actions; everything else waits for the model.
- The orchestrator sometimes says "parked" for a run that is only queued; its instructions now define the two.
- Looping is reported, not acted on: whoever reads `progress` decides to steer or cancel, by design.
