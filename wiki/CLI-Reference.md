# CLI reference

`python -m ariadne <command>`. Add `--watch` to any command to open the activity window too.

## Setup

| Command | Does |
|---|---|
| `doctor` | Check every dependency; changes nothing |
| `install [--system] [--models]` | Install what is missing (`--system`: git, uv, ollama, node; `--models`: fetch the default models now) |
| `models [list \| install NAME... \| install --defaults]` | The model catalog |
| `resources [max\|shared\|light]` | How much of the machine the models may take |

## Run

| Command | Does |
|---|---|
| `up [--lan]` / `down` | Start or stop the models and the MCP endpoint |
| `task submit TEXT --workspace DIR [--flow F] [--gate G]... [--session S]` | Give a task (or `--file brief.md`) |
| `task gates ID GATE...` | Answer a gates question |
| `task wait ID` / `task get ID` / `task list` | Follow a task |
| `task approve ID [--model N=MODEL]` / `revise ID "feedback"` / `cancel ID` | Sign off |
| `chat [--session NAME]` | Talk to Hermes in the terminal |
| `desktop [--cwd DIR] [--build] [--restart]` | Ariadne Desktop |
| `connect [--host H]` | Print MCP client configs (Claude Code, Claude Desktop, others) |

## Control

| Command | Does |
|---|---|
| `watch [--open\|--always\|--never]` | Live activity |
| `park [--resume \| --status]` | Pause the running task at its next step boundary, or resume it |
| `stop` | Stop the worker, gateways and models; running tasks come back to you |
| `browser [status \| debug on\|off]` | Attach the models' browser to your Chrome for logins, or go back to isolated |
| `kv [list \| drop SESSION]` | Parked KV caches |
| `sessions` | Sessions, their tasks and last handoff brief |
| `casestudy export WORKSPACE NAME` | Snapshot a workspace into `case_study/projects/NAME` |

## MCP tools

| Server | Tools |
|---|---|
| `ariadne-tasks` (for Claude and other callers) | `submit_task`, `set_gates`, `wait_task`, `approve_task`, `revise_task`, `cancel_task`, `get_task`, `list_tasks`, `list_sessions`, `feedback_task`, `list_skills`, `get_skill`, `save_skill` |
| `jobs` (for the local models) | `submit_job`, `list_jobs`, `job_result`, `need_login` |
| `web` (for the local models) | `web_fetch` |
