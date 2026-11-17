<p align="center"><img src="docs/img/ariadne.jpg" alt="Ariadne in Naxos, Evelyn De Morgan, 1877" width="720"></p>

# Ariadne

A local-model coding agent built on [Hermes Agent](https://github.com/NousResearch/hermes-agent). Give it a task from
the terminal or from Claude (MCP); it plans with read-only tools, sends you a backbrief with a model chosen for
each step, and only executes after you sign off. Models run on your GPU. **Status: beta, coding flow.**

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
signed-off plan uses them; add `--models` to fetch the defaults now (~38 GB). Check only: `python -m ariadne doctor`.

Then activate the environment: `source .venv/bin/activate` (Linux/macOS) or `.venv\Scripts\activate` (Windows).

## Run

```sh
python -m ariadne up          # models + MCP endpoint on 127.0.0.1:8791 (add --lan for other machines)
```

**Terminal**

```sh
python -m ariadne chat        # chat with Hermes; ask it to give Ariadne a task
python -m ariadne task submit "Fix the failing test" --workspace /path/to/repo --wait 900
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

| Use | Default | Also |
|---|---|---|
| Coding | Qwen3.8 27B (slow on 8 GB GPUs) | DeepSeek V4.1 Flash (~100 GB), Qwen3.5 9B (fast) |
| Design | Gemma 4 12B | |
| Writing | Fimbulvetr 11B v2 (drafts via an agent model) | |
| Images | Z-Image-Turbo | SD Turbo |

## Configure

- Flows: `flows/coding/flow.yaml` (model, skills, MCP servers, checks, `network.blocklist`, `browser.real_logins`).
- Models: `serving/models.yaml` (role defaults, Hugging Face source, llama-server args).
- MCP servers a flow can use: `flows/mcp_servers.yaml` (memory, git, vscode, browser, export, image, text).
- Shared memory, tasks and logs: `.ariadne/`.

## TODO

- Slack channel
- Writing and content flows (`flows/_experimental/`)

## License

MIT (`LICENSE`). Hermes Agent: MIT, Nous Research. Image: *Ariadne in Naxos*, Evelyn De Morgan, 1877 (public domain).
