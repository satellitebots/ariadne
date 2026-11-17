# Ariadne

A local-model agent harness built on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research.

Ariadne does not fork Hermes. It runs a pinned, unmodified Hermes (`upstream\`, a git submodule; clone with `--recursive`) and adds
what sits around it: flows, a task orchestrator with a brief / backbrief / sign-off / execute drill, a durable
shared memory, MCP servers, plugins and local model serving. Models are local only (llama.cpp via llama-swap,
Ollama as fallback); tools and chat channels may use the internet.

- Plan and rules: `PLAN.md`
- Progress and measurements: `WORKLOG.md`

## How it fits together

```
Slack, terminal (CLI) ------------> Hermes gateway --+
                                                       +--> task orchestrator --> Hermes worker --> local models
Claude, other MCP clients ---> ariadne-tasks (MCP) --+    (brief, backbrief,    (set up by the     (llama-swap)
                                                            sign-off)              chosen flow)  --> MCP tools
                          shared memory (durable, every task reads and writes it)                   (git, ...)
```

| Piece | Where |
|---|---|
| Flows (one folder each; add a folder to add a flow) | `flows\<name>\flow.yaml`, `flows\<name>\skills\`, `flows\mcp_servers.yaml` |
| Task orchestrator + single worker process | `ariadne\orchestrator.py` |
| MCP server for giving tasks (Claude, the gateway) | `ariadne\tasks_mcp.py` |
| Shared memory (SQLite graph + full-text search) and its MCP server | `ariadne\memory.py`, `ariadne\memory_mcp.py` |
| Git MCP server for workers | `ariadne\git_mcp.py` |
| Plan phase is read-only (Hermes plugin) | `plugins\ariadne_phase\` |
| Gateway profile + skill (CLI / Desktop / Slack use the orchestrator) | `profiles\ariadne\` |
| Local model serving | `serving\`, `tools\serve.ps1` |

Supported entry points: **Slack**, the **terminal** (Hermes CLI or `python -m ariadne.orchestrator`) and **MCP**
(Claude and other large models hand work to Ariadne).

## Install

Windows 10/11 with an NVIDIA GPU (8 GB is enough). One command checks every dependency and installs what is
missing (git, uv, Node.js, Ollama, Chrome via winget; Hermes at the pinned commit; the Python env from Hermes's
lockfile; llama.cpp, llama-swap, Pandoc, stable-diffusion.cpp and SD Turbo by sha256; the Ollama models):

```powershell
powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Check    # what is missing, changes nothing
powershell -ExecutionPolicy Bypass -File tools\install.ps1           # install it (add -Slack for the Slack channel)
```

It runs natively, not in a container: the models need the GPU and the browser/editor tools need your desktop.

## Host and connect

```powershell
powershell -ExecutionPolicy Bypass -File tools\host.ps1              # models + tasks endpoint on loopback
powershell -ExecutionPolicy Bypass -File tools\host.ps1 -Lan         # tasks endpoint for other machines (token)
powershell -ExecutionPolicy Bypass -File tools\host.ps1 -Install     # same, at every logon (scheduled task)
.venv\Scripts\python.exe -m ariadne.host connect --host <name or IP> # client configs with the token
```

The tasks endpoint is `http://<host>:8791/mcp` (MCP streamable HTTP); every request needs
`Authorization: Bearer <token>` (`.ariadne\token`, rotate with `python -m ariadne.host token --rotate`). Models
stay on loopback; other machines give Ariadne tasks, they do not call the models. For `-Lan`, allow TCP 8791 in
Windows Firewall for private networks.

## Using it

Give a task from the command line:

```powershell
$env:PYTHONPATH = "$PWD"
.venv\Scripts\python.exe -m ariadne.orchestrator submit "Fix the failing test" --workspace C:\path\to\repo
.venv\Scripts\python.exe -m ariadne.orchestrator wait <id>      # returns with the backbrief
.venv\Scripts\python.exe -m ariadne.orchestrator approve <id>   # or: revise <id> "feedback" / cancel <id>
.venv\Scripts\python.exe -m ariadne.orchestrator wait <id>      # returns with the report
```

From Hermes (the terminal, or Slack once its tokens are set), with `HERMES_HOME=.hermes-home`:

```powershell
.venv\Scripts\hermes.exe chat -s ariadne-tasks -q "Give Ariadne this task for C:\path\to\repo: ..."
```

From Claude or any MCP client, register the MCP server:

```json
{"mcpServers": {"ariadne-tasks": {"command": "C:\\repos\\ariadne\\.venv\\Scripts\\python.exe",
  "args": ["-m", "ariadne.tasks_mcp"], "env": {"PYTHONPATH": "C:\\repos\\ariadne"}}}}
```

Tools: `submit_task`, `wait_task` (the callback: returns when the backbrief or report is ready), `get_task`,
`approve_task`, `revise_task`, `cancel_task`, `list_tasks`. `tools\mcp_call.py e2e <workspace> "<task>" --approve`
runs the whole drill as an MCP client.

Slack: create a Slack app with Socket Mode (bot token `xoxb-`, app token `xapp-`), put `SLACK_BOT_TOKEN`,
`SLACK_APP_TOKEN` and `SLACK_ALLOWED_USERS` in `.hermes-home\.env`, add the `slack` extra
(`uv sync --project upstream --frozen --no-dev --extra mcp --extra slack`) and run `hermes gateway run`. Upstream guide:
`upstream\website\docs\user-guide\messaging\slack.md`.

## Flow settings you control (flow.yaml)

```yaml
mcp_servers: [memory, git, vscode, browser]   # from flows\mcp_servers.yaml: memory, git, vscode, browser, export
browser:
  real_logins: true        # Chrome with your logins; false = clean temporary profile
network:
  blocklist: []            # hosts this flow must not reach (subdomains included); everything else is allowed
```

One-time setup for the tools:
- **Chrome (browser server, Chrome DevTools MCP 1.13.0 via npx):** with `real_logins: true` it attaches to your
  running Chrome. Open `chrome://inspect/#remote-debugging` once and allow remote debugging; Chrome asks you to
  allow each new connection.
- **VS Code (vscode server):** the `JuehangQin.vscode-mcp-server` extension is installed; open the workspace in VS
  Code and switch the server on from its status bar item (it listens on 127.0.0.1:3000 only).
- **Export (export server):** Pandoc 3.14, pinned in `serving\bin.lock`:
  `tools\fetch-serving-bins.ps1 -Only pandoc`. Formats: docx, html, odt, epub, rtf, md, txt (PDF: from docx).

## Tests

`.venv\Scripts\python.exe -m pytest -q ariadne plugins`

## License

MIT, Copyright (c) 2026 Adnan Alam (`LICENSE`). Hermes Agent is MIT-licensed, Copyright (c) 2025 Nous Research;
its license is in `upstream\LICENSE` and ships with any Ariadne bundle.
