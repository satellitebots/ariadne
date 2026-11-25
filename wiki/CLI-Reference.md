# CLI reference

`python -m ariadne <command>`. Every task command is a verb (`ariadne/verbs.py`); positional arguments fill the verb's
required arguments in order, `--key value` sets the rest.

## Tasks and runs

| Command | Does |
|---|---|
| (none) | The machine, live runs, open drafts, tasks |
| `chat [--conversation C]` | Talk with the orchestrator |
| `draft "what you want" --flow F` | Open a draft from a template |
| `say DRAFT "message"` | One orchestrator turn about a draft |
| `draft_show DRAFT` · `draft_update DRAFT --yaml FILE` · `drop DRAFT` | Read, replace, discard a draft |
| `sign DRAFT` | Sign it: a new task, or the next version |
| `define FILE.yaml` | A whole definition as a draft (the MCP bypass, also here) |
| `tasks` · `task NAME` · `edit NAME` | Signed tasks; one task; a draft from its current version |
| `run NAME` · `schedule NAME TRIGGER` · `unschedule NAME` · `retire NAME` | Run now; set the trigger (`manual`, `now`, ISO time, cron) |
| `runs [NAME]` · `run_show RUN` (or `show RUN`) | Runs; one run's steps, checks and events |
| `park RUN` · `steer RUN "note"` · `resume RUN` · `cancel RUN` · `rerun RUN` | Steer a run |
| `machine` · `flows` | Who holds the GPU; the templates |

## Machine and setup

| Command | Does |
|---|---|
| `doctor` · `install [--system] [--models]` | Check / install dependencies |
| `models [list\|index\|install NAME]` · `resources [max\|shared\|light]` | The catalog; how much of the machine models may take |
| `ui [--port N] [--bind HOST]` | The console |
| `up [--lan]` · `down` · `connect` · `token` | The MCP endpoint |
| `watch [--open\|--always\|--never]` · `stop [--hard]` | Live activity; stop everything on purpose |
| `kv` · `browser [debug on\|off]` · `casestudy export WS NAME` · `server` · `watchdog` · `local-only` | Lower-level pieces |

MCP has the same verbs, plus `define`, `run_logs` and `events`.
