# Operations

## Start, watch, stop

```sh
python -m ariadne doctor            # check every dependency (changes nothing)
python -m ariadne up                # models + MCP endpoint; the worker starts with the first task
python -m ariadne watch --open      # live activity window
python -m ariadne stop              # stop the worker, the Hermes gateways and the models, on purpose
```

The watch window shows task events, every MCP call, jobs, the worker, the model server, and each Hermes run's tool
and model calls (tokens, latency, cache hits). Keys:

| Key | Action |
|---|---|
| **P** | Park the running task |
| **R** | Resume it |
| **S** then **Y** | Stop Ariadne |
| **Q** | Close the window |

Stopping hands a running task back to you (`needs_attention`) with its work kept. Approve it to continue.

## Processes outlive their caller

The worker and the model server run detached. Closing a terminal, ending a chat, or a remote session dropping
does not kill them. The only ways to stop them are the watch window and `ariadne stop`. Models are told never to
kill these processes themselves.

## Logs

| What | Where |
|---|---|
| Activity (tasks, MCP calls, KV, jobs) | `.ariadne/logs/activity-<day>.log` (two days kept) |
| Worker, model server | `.ariadne/logs/` |
| Each job | `.ariadne/logs/jobs/<job id>.log` |
| Each Hermes run | `.ariadne/homes/<flow>/logs/agent.log` |
| A task's events | `python -m ariadne task get <id>` |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| A task shows `executing` but nothing runs | The worker died (crash or reboot) | `python -m ariadne stop` hands the task back; approve it to continue |
| GPU busy, chat waits | A task holds the model | Park it, or wait; the desktop banner says which task |
| Every call reloads a model | Two models fighting for one slot | Keep embeddings in the CPU side group; send heavy work as [jobs](Jobs.md) |
| Terminal command timed out | Long work run in the model's terminal | It should be a job |
| PC crashes under load | RAM pinned too high | Use `shared` or `light`; `max` is capped at 80% RAM |
| Desktop asks for a gateway URL or offers an installer | Not Ariadne's build, or a broken runtime | `python -m ariadne desktop --build`; see [Desktop](Desktop.md) |
| A page needs a sign-in | The isolated browser has no logins | [Debug mode](Web-and-Browser.md) |
