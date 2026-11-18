<p align="center"><img src="docs/img/ariadne.jpg" alt="Ariadne in Naxos, Evelyn De Morgan, 1877" width="720"></p>

# Ariadne

A local-model agent harness built on [Hermes Agent](https://github.com/NousResearch/hermes-agent). Give it a task
from the terminal, the Hermes desktop app, or Claude (MCP). It plans with read-only tools, sends you a backbrief
with a model chosen for each step and the check gates it must pass, and only executes after you sign off. Then it
works step by step, checks every gate, and iterates until they pass. Everything runs on your own GPU.

**Status:** coding flow beta; design (Mermaid), writing and content flows shipped, not yet validated.

![Architecture](docs/img/architecture.png)

## Quick start

```sh
git clone --recursive https://github.com/satellitebots/ariadne && cd ariadne
uv run --no-project --python 3.14 python -m ariadne install --system
.venv\Scripts\activate                      # Windows; Linux/macOS: source .venv/bin/activate
python -m ariadne up                        # local models + MCP endpoint
python -m ariadne task submit "Add a --verbose flag" --workspace C:\path\to\repo --gate "run: pytest -q" --watch
```

Requirements: Windows, Linux or macOS (Apple Silicon); an NVIDIA GPU with 8 GB+ (or Apple Silicon); 32 GB RAM
recommended; [git](https://git-scm.com) and [uv](https://docs.astral.sh/uv/getting-started/installation/). `install`
checks every dependency and installs what is missing: Ollama and Node.js (`--system`), Hermes (git submodule), the
Python env and pinned binaries (sha256-verified). Models download the first time a signed-off plan needs them
(`--models` fetches the defaults now). `python -m ariadne doctor` checks without changing anything.

## How a task runs

![Task lifecycle](docs/img/task-lifecycle.png)

1. **Brief** - the task, its workspace and its **check gates**: how we know it is done, end to end. Commands
   (`run: pytest -q`) or outcomes a reviewer can verify ("README documents every command"). No gates, no start:
   the task waits and asks for them.
2. **Backbrief** - the worker reads the workspace (read-only) and answers with mission, steps, the model for each
   step, and which step makes each gate pass.
3. **Sign-off** - approve (optionally changing a step's model), revise with feedback, or cancel.
4. **Execute** - step by step, each step on its model; checkpoints between phases keep contexts small.
5. **QA** - command gates run, review gates are judged by a separate reviewer run. Failing gates go back to the
   worker with the reasons, up to 10 rounds; it stops early when two rounds in a row make no progress.
6. **Report** - what changed, how it was verified.

## Three ways in

### Terminal

```sh
python -m ariadne task submit --file brief.md --workspace C:\repo     # brief with a "Gates:" section
python -m ariadne task submit "Diagram the auth flow" --flow design --gate "diagrams render" --session auth
python -m ariadne task wait <id>                  # backbrief, then the report
python -m ariadne task approve <id>               # or: revise <id> "feedback" / cancel <id>
python -m ariadne task approve <id> --model 2=gemma-4-12b    # change a step's model before locking the plan
python -m ariadne task gates <id> "run: pytest -q" "README covers every command"   # answer a gates question
python -m ariadne chat                            # or talk it through with Hermes in the terminal
```

### Desktop

Ariadne Desktop is the [Hermes desktop app](upstream/apps/desktop/README.md), rebranded and locked to your local
runtime: chat with live tool output, side-by-side previews of what the worker produced (diagrams, docs, images,
diffs), a file browser, and voice.

```sh
python -m ariadne desktop --cwd C:\path\to\repo   # first launch builds the app (needs Node.js; a few minutes)
python -m ariadne desktop --build                 # rebuild (after swapping artwork in desktop/assets/)
python -m ariadne desktop --restart               # reopen with a fresh backend (after config or plugin changes)
```

The app is a focused shell: new chat and your sessions; the Hermes pages Ariadne does not use (capabilities,
messaging platforms, artifacts, scheduled jobs) are hidden. The status bar shows what the local model is doing, and
while a task holds it a banner above the message box says so. Your messages wait for the task's current run - nothing
interrupts a task on its own. To talk now, press **Park task** (or `python -m ariadne park`): the task finishes the
step in flight, parks its KV cache and waits; **Resume task** (`python -m ariadne park --resume`) wakes the cache and
continues the same session. These are a Hermes desktop plugin (`desktop/plugin`, installed into the app's home), not
changes to Hermes.

It opens straight into chat: no setup screen, no gateway URL, no installer. If the local runtime is broken it says
so and stops, instead of offering to install or connect elsewhere. The app's state lives in `.ariadne/desktop-data`,
separate from any stock Hermes install. Branding is `desktop/branding.json` plus `desktop/assets/`, applied to a
throwaway copy of Hermes at the pinned commit (`upstream/` is never edited); every edit states how many places it
expects to change, so a Hermes update that moves one stops the build and names it.

Then just ask in the chat: *"Give Ariadne a task: add a --verbose flag to the CLI in this repo. Gates: pytest
passes; README documents the flag."* The app's assistant submits it, shows you the backbrief, and waits for your
approve / revise / cancel before anything changes. Every task from one desktop conversation shares a session, so
later tasks build on earlier ones.

### MCP (Claude and other large models)

```sh
python -m ariadne connect     # prints configs for Claude Code, Claude Desktop and other MCP clients
```

`submit_task` (with `gates`), `set_gates`, `wait_task`, `approve_task`, `revise_task`, `cancel_task`, `get_task`,
`list_tasks`, `list_sessions`, `feedback_task`, `list_skills`, `get_skill`, `save_skill`.

## Watch it work

Everything Ariadne does goes to `.ariadne/logs/activity-<day>.log` (one file per day, two days kept): task events,
every MCP tool call, KV cache moves. To see it live, merged with the worker, the model server and each Hermes
worker's tool and model calls (tokens, latency, cache hits):

```sh
python -m ariadne watch --open      # in its own window (or add --watch to any command)
python -m ariadne watch --always    # open it on every run; --never to stop
```

The worker and the model server run on their own, outside any terminal, chat or remote session that started them
(on Windows they break away from the caller's job, or start through WMI), so closing a window or losing a
connection never kills a task halfway. You stop them on purpose:

- in the watch window: **P** parks the running task, **R** resumes it, **S** then **Y** stops Ariadne, **Q** closes
  the window;
- or `python -m ariadne stop`.

Stopping hands a running task back to you (`needs_attention`) with its work kept; approve it to continue.

## Models

Every plan step gets a model; your sign-off locks them; nothing runs until every chosen model and tool is
installed. `python -m ariadne models` lists the catalog (`serving/models.yaml`). Sized for an 8 GB GPU with 32 GB
RAM; plans favour mixture-of-experts models, which run several times faster here.

| Use | Default | Also |
|---|---|---|
| Coding | Qwen3.6 35B-A3B (MoE, 3B active) | Qwen3.8 27B (dense, hardest steps), Qwen3.5 9B (quick steps) |
| Design | Gemma 4 26B-A4B (MoE) | Gemma 4 12B |
| Writing | Gemma 4 26B-A4B (MoE) | Gemma 4 31B (best prose, slow) |
| Images | Z-Image-Turbo | SD Turbo |
| Routing, memory | Qwen3.5 4B, Qwen3 Embedding 0.6B | |

**Resource profiles** - how much of the machine the models take (`python -m ariadne resources <profile>`, applied
between tasks): **max** fills the GPU, runs the rest on the CPU pinned in RAM at high priority; **shared** leaves
headroom at normal priority; **light** caps a model at 80% of GPU memory and 50% of RAM at low priority.

## Speed: KV cache parking and checkpoints

One GPU means models swap constantly, and every swap throws away the KV cache. Ariadne parks it instead: after a
run the cache is saved under **session + step + model**, and woken when that session resumes on that model, so
switching tasks or models costs a disk read instead of a re-read of the whole conversation (`python -m ariadne kv`;
40 GB cap, `ARIADNE_KV=off` to disable).

Small models work best with small contexts, so a session is compressed at every phase boundary: plan approved,
each step done, QA done. The model that just worked writes a handoff brief, and the next phase starts fresh from
it. Inside a run Hermes compresses past 30K tokens.

A **session** is a workstream: its tasks and the conversation between them (`--session NAME`, `session` on MCP,
or one per desktop or terminal chat; `python -m ariadne sessions`).

## Jobs, the web and logins

Models write; Ariadne runs. Heavy work (installs, ingest, builds, evals, full test suites) is written as a script
and handed over with `submit_job`. Ariadne parks the model's cache, unloads the models, runs the job outside any
session (log in `.ariadne/logs/jobs/`), and wakes the same conversation with the result. No timeouts to babysit, and
the model and the heavy work never hold the machine at the same time.

Every flow can search the web (`web_search`, keyless) and read pages (`web_fetch`), and drive a visible Chrome
(browser tools). Coding looks up official docs before using an API (the `coding-standards` skill). The browser
starts isolated, with no sign-ins. Models never type passwords or codes: a step that needs a login calls
`need_login`, the task pauses, and you sign in yourself in **debug mode**, which attaches the browser tools to your
own Chrome and its existing sessions:

```
python -m ariadne browser debug on     # once in Chrome: chrome://inspect/#remote-debugging -> allow
python -m ariadne park --resume        # or R in the watch window
python -m ariadne browser debug off    # back to the isolated browser
```

## Skills

Every flow loads the shared skills in `skills/<flow>/<name>/SKILL.md`. The larger models that drive Ariadne write
them: after a task, the caller folds your feedback and its own review into a skill with `save_skill`, which commits
and pushes it. Local workers never write skills. Contributions welcome: add or improve a `SKILL.md` (frontmatter
`name` and `description`, then specific, imperative guidance) and open a pull request.

## Configure

- Flows: `flows/<name>/flow.yaml` - coding, design, writing, content (models, skills, MCP servers, checks, budgets,
  `network.blocklist`, `browser.real_logins`). Add a flow by adding a folder.
- Models, context window and resource profile: `serving/models.yaml`.
- MCP servers a flow can use: `flows/mcp_servers.yaml` (memory, jobs, web, git, vscode, browser, export, image, diagram, text).
- State (tasks, sessions, memory, KV caches, logs): `.ariadne/`.

## TODO

- Slack channel
- Validate the design, writing and content flows
- One Python environment per workspace, shared by the worker's terminal and the gate commands

## License

MIT (`LICENSE`). Hermes Agent: MIT, Nous Research. Image: *Ariadne in Naxos*, Evelyn De Morgan, 1877 (public domain).
