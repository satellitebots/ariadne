# CLI reference

`ariadne <command>` (or `python -m ariadne <command>`).

| Command | What it does |
|---|---|
| *(none)* | the inbox: what needs you, what is running, what finished |
| `"a brief"` | one gesture: this folder, this session, followed live |
| `submit "text" --flow F --model M` | give a task (also `--file`, `--gate`, `--workspace`, `--session`) |
| `inbox` / `show [ID]` / `follow [ID]` | state, one card, live activity |
| `ok [ID]` / `fix [ID] "feedback"` / `no [ID]` / `gates ID ...` | sign off, revise, cancel, answer the gates |
| `task ...` | the same verbs: submit / wait / approve / revise / cancel / list / get |
| `sessions` | sessions: tasks, segments, last handoff |
| `schedules ...` | standing briefs (create / on / off / rm) |
| `chat [--session NAME]` | the conversation bound to a session; submits, never works |
| `ui [--port N]` | the console (loopback by default; `ARIADNE_BIND` for the LAN) |
| `watch` | live activity |
| `models [list]` | the catalog |
| `models index [--json] [--pulse KIND] [--refresh]` | what this machine can run, by tier |
| `models install NAME...` | fetch and verify weights |
| `resources [max\|shared\|light]` | how much of the machine models may take |
| `kv [list\|drop]`, `park [--resume\|--status]` | parked caches, pausing |
| `browser [status\|debug on\|off]` | the models' browser and its logins |
| `up [--lan]` / `down` / `stop` | model server + MCP endpoint; stop everything |
| `connect [--host H]` | print MCP client configs |
| `doctor` / `install [--system] [--models]` | check; install what is missing |
| `serve` / `profile` / `flows` / `token` | lower-level pieces |

`desktop` is retired: `ariadne ui` is the console.
