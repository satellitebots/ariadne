<p align="center"><img src="docs/img/ariadne.jpg" alt="Ariadne in Naxos, Evelyn De Morgan, 1877" width="720"></p>

# Ariadne

A **local-only task harness**. Give it a brief and it answers with a plan, a model chosen for each step and the check
gates it must pass; it executes only after you sign off, then works step by step, checks every gate, and iterates until
they pass. Everything runs on your own machine.

Ariadne is an **orchestrator**; the agent that does the work is [Hermes Agent](https://github.com/NousResearch/hermes-agent),
pinned as a submodule (`vendor/hermes`) and overlaid - never edited. We keep Hermes's loop, tools, skills, MCP client,
context handling and provider plumbing as the worker backend, and replace only the surfaces whose integration point
belongs to the orchestrator: the desktop app, the chat and the MCP hosting surface. The rest of Hermes - messaging,
bots, connectors, cloud providers, telemetry, the desktop shell - is present in the tree but never started.

**Status:** 0.1.1. Four flows (`coding`, `design`, `investigation`, `content`), 301 model-free tests, the drill proven
end to end against a scripted model. No flow has been run against a live model yet; that is the deferred GPU item.

**[Wiki](wiki/Home.md)** · [release notes](https://github.com/satellitebots/ariadne/releases/tag/ariadne-0.1.1) ·
[the fork and the overlay](docs/FORK.md) · [backlog](docs/BACKLOG.md)

![Architecture](docs/img/architecture.png)

## Quick start

```sh
git clone --recurse-submodules https://github.com/satellitebots/ariadne && cd ariadne
uv run --no-project --python 3.14 python -m ariadne install --system   # venv from vendor/hermes, system tools, bins
.venv\Scripts\activate                                                 # Windows; Linux/macOS: source .venv/bin/activate
python -m ariadne doctor                # what is missing (changes nothing)
python -m ariadne models index          # what this machine can run, by tier
python -m ariadne up                    # model server + MCP endpoint
python -m ariadne ui                    # the console at http://127.0.0.1:8917
python -m ariadne submit "Add a --verbose flag" --flow coding --model qwen3.6-35b-a3b \
    --workspace C:\path\to\repo --gate "run: pytest -q" --watch
```

Requirements: Windows, Linux or macOS (Apple Silicon); an NVIDIA GPU with 8 GB+ (or Apple Silicon); 32 GB RAM
recommended; [git](https://git-scm.com) and [uv](https://docs.astral.sh/uv/getting-started/installation/). `install`
builds the venv from the pinned Hermes lockfile, installs what is missing (Ollama and Node.js with `--system`) and
fetches the pinned binaries (sha256-verified). Models download the first time a signed-off plan needs them (`--models`
fetches the defaults now).

## How a task runs

![Task lifecycle](docs/img/task-lifecycle.png)

1. **Brief** - the task, its workspace and its **check gates**: how we know it is done. Commands (`run: pytest -q`)
   or outcomes a reviewer can verify. No gates, no start: the task waits and asks for them.
2. **Backbrief** - the worker reads the workspace with read-only tools and answers with mission, steps, the model for
   each step, and which step makes each gate pass.
3. **Sign-off** - approve (optionally changing a step's model), revise with feedback, or cancel.
4. **Execute** - one session per task; a step that needs a different agent model starts the next link of the chain with
   a handoff brief. The planner is unloaded after sign-off and reloaded for the work.
5. **QA** - command gates run; review gates are judged by a separate reviewer run. Failing gates go back to the worker
   with the reasons, up to 10 rounds, stopping early when two rounds make no progress.
6. **Report** - what changed, how it was verified.

Out of wall-clock or out of turns is not failure: the work stays and the gates decide.

## Four ways in

### Console

```sh
python -m ariadne ui        # http://127.0.0.1:8917, loopback by default
```

Sessions as the only navigation; the backbrief as a document; only the verbs legal for a task's status; live activity
over SSE. The same verbs as the terminal (`submit`, `steer`, `gates`, `ok`, `fix`, `no`) - one experience, four surfaces.

### Terminal

```sh
python -m ariadne "fix the failing date test"          # one gesture: this folder, this session, watched live
python -m ariadne submit --file brief.md --flow design --model gemma-4-12b
python -m ariadne inbox                               # what needs you, what is running, what finished
python -m ariadne show <id>                           # the backbrief as a person reads it
python -m ariadne ok <id>                             # approve; --model 2=gemma-4-12b changes a step
python -m ariadne fix <id> "use pytest, not unittest" # send it back to planning
python -m ariadne no <id>                             # cancel
python -m ariadne gates <id> "run: pytest -q" "README covers every command"
python -m ariadne steer <id> "use pytest, not unittest"   # guide it while it runs
python -m ariadne stop                                  # kill switch: the whole Ariadne group
```

`inbox`, `show` and `follow` never call a model, so they work while the GPU is busy or the models are down.

### Chat

```sh
python -m ariadne chat --session my-repo
```

A conversation bound to one session. It can talk, look things up read-only, and submit a task; it **cannot** do the
work - it runs with `native_tools=False`, so the file, patch, search-in-files and terminal tools do not exist in that
conversation.

### MCP (Claude and other large models)

```sh
python -m ariadne connect     # configs for Claude Code, Claude Desktop and other MCP clients
```

`submit_task`, `set_gates`, `wait_task`, `approve_task`, `revise_task`, `cancel_task`, `get_task`, `list_tasks`,
`list_sessions`, `get_status`, `feedback_task`, `list_skills`, `get_skill`, `save_skill`.

## Models

Every plan step gets a model; sign-off locks them; nothing runs until every chosen model and tool is installed.
`python -m ariadne models` lists the closed catalog (`serving/models.yaml`).

**The index** (`python -m ariadne models index`) measures the machine at startup and gives every model a deterministic
verdict: `gpu` (weights + a fixed 1.5 GB fits in 90% of VRAM), `hybrid` (fits the resource profile's total, part on the
CPU; MoE models note why that costs less), or `no` with both numbers in the reason. The planner's menu uses the same
rule. `--pulse agent|image|embed` asks Hugging Face for the most downloaded models of that task, filters them by the
same arithmetic and caches for a day; suggestions never edit the catalog.

| Use | Default | Also |
|---|---|---|
| Coding | Qwen3.6 35B-A3B (MoE, 3B active) | Qwen3.8 27B (dense, hardest steps), Qwen3.5 9B (quick steps) |
| Design | Gemma 4 26B-A4B (MoE) | Gemma 4 12B |
| Content | Gemma 4 26B-A4B (MoE) | Gemma 4 31B (best prose, slow) |
| Images | Z-Image-Turbo | SD Turbo |
| Routing, memory | Qwen3.5 4B, Qwen3 Embedding 0.6B | |

**Resource profiles** (`python -m ariadne resources <profile>`, applied between tasks): **max** fills the GPU and puts
the rest on the CPU pinned in RAM at high priority; **shared** leaves headroom at normal priority; **light** caps a
model at 80% of GPU memory and 50% of RAM at low priority.

**Local-only** is enforced, not suggested: `local_only` refuses any endpoint that is not loopback, LAN or allowlisted,
and refuses any API key. A localhost/LAN Ollama server is allowed through the serving registry. Tools may still use the
internet.

## Speed: KV cache parking and checkpoints

One GPU means models swap constantly, and every swap throws the KV cache away. Ariadne parks it instead: after a run
the cache is saved under **session + step + model** and woken when that session resumes on that model, so switching
costs a disk read rather than a re-read of the conversation (`python -m ariadne kv`; 40 GB cap, `ARIADNE_KV=off`).

Small models work best with small contexts, so a session is compressed at every phase boundary: plan approved, each
step done, QA done. The model that just worked writes a handoff brief; the next phase starts from it. Inside a Hermes
run, context is compressed past 30K tokens.

## Jobs, the web and logins

Models write; Ariadne runs. Heavy work (installs, ingest, builds, evals, full test suites) is written as a script and
handed over with `submit_job`. Ariadne parks the cache, unloads the models, runs the job with the whole machine (log in
`.ariadne/logs/jobs/`), and wakes the same conversation with the result.

Every flow can search the web (`web_search`, keyless) and read pages (`web_fetch`), and drive a visible Chrome. The
browser starts isolated, with no sign-ins; a step that needs a login calls `need_login`, the task pauses, and you sign
in yourself in **debug mode** (`python -m ariadne browser debug on`), which attaches the browser to your Chrome and
its sessions.

## Skills

Every flow loads `skills/common/*` and `skills/<flow>/*`. The plan prompt lists name and description; `skill_view`
returns the body, so a run can follow a skill instead of only knowing it exists. The larger models that drive Ariadne
write them (`save_skill`, which commits and pushes); local workers never write skills. Contributions welcome.

## The backend, and updates

The worker runs Hermes at the pin in `vendor/hermes` (a submodule; `worker.hermes_run` is the default runner). The venv
is built from that checkout's own lockfile. `ariadne/runtime/` is a complete fallback loop (`ARIADNE_RUNTIME=own`).

When a module genuinely has to differ, the file goes in `overlay/<package>/<module>.py`; `bootstrap.start()` puts the
repo root and `vendor/hermes` ahead of site-packages and prepends the overlaid package's path, so our file wins for that
module while every other module still comes from the submodule. `overlay.yaml` records module, reason and test, and
`overlay.check()` fails the suite if one is missing.

Updates are a pointer bump plus a resync:

```sh
python tools/sync_hermes.py --to v0.24.0    # fetch, checkout, stage the pointer, uv sync from its lockfile
pytest -q                                   # test_hermes_contract names any flag, key or hook that moved
```

## Configure

- Flows: `flows/<name>/flow.yaml` - coding, design, investigation, content. Add a flow by adding a folder.
- Models, context window and resource profile: `serving/models.yaml`.
- MCP servers a flow may name: `flows/mcp_servers.yaml` (memory, jobs, web, git, browser, vscode, export, image,
  diagram, text, data, office, ci, rag).
- State (tasks, sessions, memory, KV caches, logs): `.ariadne/`.

## Docs

`docs/FORK.md` (the fork and the overlay), `DESIGN-RESET.md` (the drill), `FRONTEND.md` (console and chat),
`MODELS.md`, `MCP.md`, `COVERAGE.md` (per-flow tool coverage), `GAP-ANALYSIS.md`, `BACKLOG.md`.

**Forced differences from Hermes:** local inference only; no messaging (Telegram/Slack/Discord are not surfaces
Ariadne has); and **flows replace bots** - a flow is `flow.yaml` + `FLOW.md` + skills + gates, and a person signs off a
plan, not a persona with a soul file.

## License

MIT (`LICENSE`). Hermes Agent: MIT, Nous Research. Image: *Ariadne in Naxos*, Evelyn De Morgan, 1877 (public domain).
