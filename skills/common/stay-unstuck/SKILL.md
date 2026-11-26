---
name: stay-unstuck
description: Rules that keep a step moving - never repeat a call that already answered, finish one deliverable at a time, write scripts instead of poking. Applies to every step.
---
# Stay unstuck

You work one step at a time on a long context, and a step can slide into repeating itself (one ran the same `ls`
266 times). Everything you do is logged live; repeated calls are reported as looping.

- **A call that already answered is answered.** If you are about to make a call you made before with the same
  arguments, stop: use the result you have, or do something different.
- **After writing a script, run it** (or `submit_job` it if it is heavy) straight away, then stop and wait. Do not
  list, re-read or delete it first. Never delete finished outputs (`.venv`, `data/`) to start over; fix and rerun.
- **One deliverable at a time.** Finish the file the step asks for, check it, then report. If the step needs more
  than about thirty tool calls, say so in your report instead of grinding on.
- **Scripts over poking.** To learn something about data, write a short script that prints what you need, rather
  than many small reads and greps.
- **When something fails twice the same way,** read the error once more, change the approach, and if you still
  cannot, reply `OFF-PLAN:` with what is missing.
