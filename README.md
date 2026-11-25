<p align="center"><img src="docs/img/ariadne.jpg" alt="Ariadne in Naxos, Evelyn De Morgan, 1877" width="720"></p>

# Ariadne

**Durable tasks on local models.** With the help of a local orchestrator you define a task (a chain of steps, each
with the files it must leave and how it is checked), sign it, and run it now or on a schedule. Workers do the steps,
one at a time, on your own machine; one GPU is shared through a lease so the orchestrator, the workers and heavy
jobs never fight over it.

- **One front.** The console, the chat, the terminal and MCP are generated from the same verbs
  (`ariadne/verbs.py`); none has a feature the others lack. MCP is also the bypass: an outside agent (Claude) can hand
  in a whole definition, so the local orchestrator never loads.
- **The orchestrator defines; workers do.** The orchestrator has no tool that writes a file or runs a command. Each
  step is one headless [Hermes Agent](https://github.com/NousResearch/hermes-agent) run (`vendor/hermes`, pinned and
  never edited).
- **One owner of the machine.** The broker (`ariadne/broker.py`) alone loads and unloads models. A running step keeps
  the machine until its boundary; you park it to take the machine now. Steering is park, then steer, then resume.

**Status:** the redesign of 24-25 Nov (`docs/DESIGN.md`). Investigation is the first flow rebuilt as a template.

**[Wiki](wiki/Home.md)** Ã‚Â· [design](docs/DESIGN.md) Ã‚Â· [backlog](docs/BACKLOG.md)

## Quick start

```sh
git clone --recurse-submodules https://github.com/satellitebots/ariadne && cd ariadne
uv run --no-project --python 3.14 python -m ariadne install --system
.venv\Scripts\activate                     # Windows; Linux/macOS: source .venv/bin/activate
python -m ariadne doctor                   # what is missing (changes nothing)
python -m ariadne ui                       # the console at http://127.0.0.1:8917
python -m ariadne chat                     # or talk to the orchestrator in the terminal
```

Requirements: Windows, Linux or macOS (Apple Silicon); an NVIDIA GPU with 8 GB+ (or Apple Silicon); 32 GB RAM
recommended; [git](https://git-scm.com) and [uv](https://docs.astral.sh/uv/getting-started/installation/).

## How a task runs

1. **Draft.** Say what you want and pick a flow (a template: investigation, coding, design, content). The
   orchestrator fills in the template with you: the parameters, a name, the workspace, when it runs.
2. **Sign.** The definition is YAML you can read and edit. Signing makes it a version; editing later makes the next
   version, and runs in progress finish on the version they started.
3. **Run.** Now, at a time, or on a cron schedule (`weekdays at 07:00`). A missed schedule runs once, not once per miss.
4. **Steps.** Each step is one worker with only the step's tools. Steps hand over through files. Heavy work
   (installs, data pulls, test suites) is a job: the worker writes a script, the models are unloaded, the job runs,
   and the worker is woken with the result.
5. **Checks.** A step's check (a command, or a read-only reviewer) must pass; a failure is retried once with the
   reasons, then the run asks for you. Task gates are checked after the last step.

## The ways in

```sh
python -m ariadne                       # what is going on: the machine, live runs, drafts, tasks
python -m ariadne chat                  # the orchestrator: define tasks, start, park, steer, resume runs
python -m ariadne draft "what you want" --flow investigation
python -m ariadne say <draft> "weekdays at 7, in C:/work/googl"
python -m ariadne sign <draft>
python -m ariadne run googl-daily       # schedule googl-daily "0 7 * * 1-5"
python -m ariadne park <run>  Ã‚Â·  steer <run> "use weekly bars"  Ã‚Â·  resume <run>  Ã‚Â·  cancel <run>
python -m ariadne machine               # who holds the GPU, who waits
python -m ariadne connect               # MCP configs for Claude Code, Claude Desktop and other clients
```

The console (`ariadne ui`) shows the same things: the machine bar, tasks and drafts, each run drawn as a thread
through its steps, and the orchestrator beside every page.

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
each step's cache is saved under **run + step + model** and woken when that step resumes (after a park or a job), so
switching costs a disk read rather than a re-read of the conversation (`python -m ariadne kv`; 40 GB cap,
`ARIADNE_KV=off`). Steps start fresh and hand over through files, so contexts stay small; inside a Hermes run, context
is compressed past 30K tokens.

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

Each step runs Hermes at the pin in `vendor/hermes` (a submodule; `engine.hermes_step`). The venv is built from that
checkout's own lockfile. `ariadne/runtime/` is the small loop the orchestrator's conversation runs on.

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
