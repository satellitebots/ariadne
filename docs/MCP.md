# Integrating with Ariadne over MCP

Ariadne is a local task harness: you give it a brief, it plans with read-only tools, a person signs off, and a
worker executes on a **local model** until the check gates pass. This server is how another agent (Claude, Hermes,
anything MCP-speaking) drives that drill. Every model behind it runs on this machine or this LAN; no API key, no
token spend.

## Transports

**stdio** - simplest, one process per client:

```json
{
  "mcpServers": {
    "ariadne_tasks": {
      "command": "C:/repos/ariadne/.venv/Scripts/python.exe",
      "args": ["-m", "ariadne.tasks_mcp"],
      "env": { "PYTHONPATH": "C:/repos/ariadne" }
    }
  }
}
```

**HTTP** - `ariadne up` starts the models and the endpoint at `http://<host>:8791/mcp` with a bearer token
(`ariadne token`). Use this when several clients share one worker, or when the models live on another machine in
the same network.

In Hermes the tools appear as `mcp__ariadne_tasks__<tool>`.

## The drill

Call **`get_choices` first**. It returns this list plus the two closed sets you must pick from:

1. `get_choices` - approved flows and agent models. A name outside them is refused, not guessed.
2. `submit_task(text, flow, model, gates, workspace, session)` - `gates` say how we know it is done, end to end
   (`"run: pytest -q"` for a command, plain prose for a reviewer outcome). Ask the person if they did not give them;
   without gates the task waits.
3. `wait_task(id)` - returns the card. Call again while it says *Working*.
4. On **backbrief ready**: show the person the card **verbatim**. They decide; you call `approve_task`,
   `revise_task` or `cancel_task`. Never sign off on their behalf.
5. After approval the worker runs; `wait_task` again until **done**, **failed**, or **needs you**.
6. `get_status` answers "what is happening?" without touching a task; `get_task` re-reads one card.

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `get_choices` | - | the drill, approved flows, approved agent models |
| `submit_task` | `text`, `flow`, `model`, `gates?`, `workspace?`, `session?`, `source?` | the task card |
| `wait_task` | `id`, `timeout_seconds?` (1-280) | the card, after it changes or times out |
| `get_task` | `id` | the card |
| `get_status` | - | the inbox (needs you / running / stopped / recent) plus what holds the model |
| `approve_task` | `id`, `models?` (`"2=gemma-4-12b"` or `"all=qwen3.6-35b-a3b"`) | the card |
| `revise_task` | `id`, `feedback` | the card - it goes back to planning and produces a **new** backbrief |
| `set_gates` | `id`, `gates` | the card |
| `cancel_task` | `id` | the card |
| `feedback_task` | `id`, `feedback` | the card - notes for a finished or stopped task |
| `list_sessions` | `limit?` | the durable workstreams and their tasks |
| `list_skills` / `get_skill` / `save_skill` | `flow`, `name`, `content?` | shared skills the next plan will read |

`flow` and `model` are **required** on `submit_task`. A task that enters over MCP must be one the desktop and the
terminal would accept - the three doors share one rulebook (`ariadne/service.py`) and one document
(`ariadne/present.py`).

## The card

Every task tool returns the same Markdown card, so you can show it to the person as-is:

```
## Task t1120-1015-ab12 - queued

- flow: coding  ·  model: qwen3.6-35b-a3b  ·  session: proj  ·  workspace: C:/repos/proj

**Brief:** fix the failing leap-year test

**Check gates:**
- run: pytest -q

**You may:** cancel

**Next:** Working. Call wait_task again.

```json
{"id": "...", "status": "new", "flow": "coding", "session": "proj", "actions": ["cancel"], "next": "..."}
```
```

The fenced JSON at the end is the machine-readable tail: `status`, and `actions` - the verbs that are legal right
now. Prefer `actions` over inferring from `status`.

## Errors

Tools never raise. A refusal comes back as `{"error": "..."}` with the reason and, where useful, the approved list:

```json
{"error": "'writing' is not an approved flow; approved: coding, content, design, investigation"}
{"error": "name the model for this task; approved: qwen3.6-35b-a3b, qwen3.8-27b, gemma-4-12b, ..."}
```

Show that message to the person rather than retrying with a guess.

## What a client must not do

- invent a flow, a model or a tool name - the sets are closed and a miss is refused;
- approve a backbrief the person has not seen;
- paste the result of the work into the conversation instead of submitting a task;
- assume the worker is running: `get_status` says whether a worker holds the model, and a task left `executing`
  with no worker is reported as **stopped**.
