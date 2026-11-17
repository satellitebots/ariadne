<p align="center"><img src="docs/img/ariadne.jpg" alt="Ariadne in Naxos, Evelyn De Morgan, 1877" width="720"></p>

# Ariadne

A local-model coding agent built on [Hermes Agent](https://github.com/NousResearch/hermes-agent). Give it a task from
the terminal or from Claude (MCP); it plans with read-only tools, sends you a backbrief with a model chosen for
each step, and only executes after you sign off. Models run on your GPU.

**Status:** coding flow beta; design (Mermaid), writing and content flows shipped, not yet validated.

![Architecture](docs/img/architecture.png)

## Requirements

- Windows, Linux or macOS (Apple Silicon); an NVIDIA GPU with 8 GB+ (Windows/Linux) or Apple Silicon
- [git](https://git-scm.com) and [uv](https://docs.astral.sh/uv/getting-started/installation/); the installer adds the rest

## Install

```sh
git clone --recursive https://github.com/satellitebots/ariadne && cd ariadne
uv run --no-project --python 3.14 python -m ariadne install --system
```

`install` checks every dependency first and installs what is missing: Ollama and Node.js (`--system`), Hermes
(git submodule), the Python env and pinned binaries (sha256-verified). Larger models are fetched the first time a
signed-off plan uses them; add `--models` to fetch the defaults now (~50 GB). Check only: `python -m ariadne doctor`.

Then activate the environment: `source .venv/bin/activate` (Linux/macOS) or `.venv\Scripts\activate` (Windows).

## Run

```sh
python -m ariadne up          # models + MCP endpoint on 127.0.0.1:8791 (add --lan for other machines)
```

**Terminal**

```sh
python -m ariadne chat        # chat with Hermes; ask it to give Ariadne a task
python -m ariadne task submit "Fix the failing test" --workspace /path/to/repo --wait 900
python -m ariadne task submit "Diagram the auth flow" --flow design --session auth-work   # continue a session
python -m ariadne task approve <id>     # or: revise <id> "feedback" / cancel <id>
python -m ariadne task approve <id> --model 2=gemma-4-12b   # change a step's model, then lock the plan
python -m ariadne task wait <id>        # the report
```

**MCP (Claude, other large models)**

```sh
python -m ariadne connect     # prints configs for Claude Code, Claude Desktop and other MCP clients
```

Tools: `submit_task`, `wait_task`, `approve_task`, `revise_task`, `cancel_task`, `get_task`, `list_tasks`.

![Task lifecycle](docs/img/task-lifecycle.png)

## Models

Each step of a plan gets a model; your sign-off locks them, and nothing runs until every chosen model and tool is
installed. `python -m ariadne models` lists them.

Sized for an 8 GB GPU with 32 GB of RAM; larger models run partly on the CPU. Plans favour the mixture-of-experts models (3-4B active parameters): they prefill and generate several times faster here.

| Use | Default | Also |
|---|---|---|
| Coding | Qwen3.8 27B (slow) | Qwen3.6 35B-A3B (MoE, faster), Qwen3.5 9B (quick steps) |
| Design | Gemma 4 26B-A4B (MoE) | Gemma 4 12B |
| Writing | Gemma 4 26B-A4B (MoE) | Gemma 4 31B (best prose, slow) |
| Images | Z-Image-Turbo | SD Turbo |
| Routing, memory | Qwen3.5 4B, Qwen3 Embedding 0.6B | |

## KV cache parking

One GPU means models swap constantly - planner, coder, writer; this task, then that one. Every swap normally
throws away the KV cache, and the next turn re-reads the whole conversation (minutes on a 27B partly on the CPU).
Ariadne parks it instead:

- After every run, the model's KV cache is saved to disk under **session + step + model** (`plan`, `step-1-3`, ...),
  and becomes that session's **master** cache for the model.
- Before a run, the step's own cache wakes (a retry or re-run of that step), else the session's master; prefill
  is skipped for everything already seen.
- Switching tasks, swapping models between steps, or resuming a conversation tomorrow costs a disk read.

A cache belongs to one model (another model's weights cannot use it); the conversation itself carries across
models through the session. Caches are capped at 40 GB (least recently used go first; `ARIADNE_KV_MAX_GB`),
listed with `python -m ariadne kv`, and off with `ARIADNE_KV=off`.

## Sessions and checkpoints

A **session** is a workstream: every task given in it, and the conversation that carries between them. Each task
gets its own session unless you name one - `--session NAME` (CLI), `session` (MCP), or just chat: tasks given in
`python -m ariadne chat` join that chat's session, and `chat --session NAME` continues a named one.
`python -m ariadne sessions` lists them.

Small local models work best with small contexts, so a session is compressed at every phase boundary - the drill
again: the plan is approved, **checkpoint**; each step finishes, **checkpoint**; QA runs, **checkpoint**; then report
or retry. At a checkpoint the model that just worked (still loaded, cache hot) writes a handoff brief - situation,
done, state, open - and the next phase starts a fresh Hermes session seeded with it. A new task in the same
session starts from the last brief. Inside a run, Hermes also compresses past 30K tokens (`context` in
`serving/models.yaml`).

## Configure

- Flows: `flows/<name>/flow.yaml` - coding, design, writing, content (model, skills, MCP servers, checks,
  `network.blocklist`, `browser.real_logins`).
- Models: `serving/models.yaml` (role defaults, Hugging Face source, llama-server args).
- MCP servers a flow can use: `flows/mcp_servers.yaml` (memory, git, vscode, browser, export, image, diagram, text).
- Shared memory, tasks and logs: `.ariadne/`.

## TODO

- Slack channel
- Validate the design, writing and content flows

## License

MIT (`LICENSE`). Hermes Agent: MIT, Nous Research. Image: *Ariadne in Naxos*, Evelyn De Morgan, 1877 (public domain).
