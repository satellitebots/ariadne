# Architecture

```
 console (ariadne ui)   chat (ariadne chat)   terminal   MCP (Claude, other agents)
          \                  |                  |              /
           +------------- verbs.py (one contract) ------------+
                    |                         |
            orchestrate.py              durable.py (tasks, versions, drafts, runs, events)
         (local model, no doing-tools)        |
                    |                   daemon.py -> engine.py (scheduler + runs, step by step)
                    |                         |              \
                    +------- broker.py (one lease) ---------- jobs.py (models unloaded)
                                   |
                          llama-swap / llama.cpp     Hermes (vendor/hermes), one headless run per step
```

| Piece | What it is | Where |
|---|---|---|
| Verbs | Every action any front can take; MCP tools, HTTP routes and the chat's tools are generated from it | `ariadne/verbs.py` |
| Fronts | MCP (`front_mcp.py`, also as `tasks_mcp`), HTTP + the React console (`server/app.py`, `ui/`), the terminal (`__main__.py`) | |
| Store | Tasks and their signed versions (also as YAML under `.ariadne/tasks/<id>/v<N>.yaml`), drafts, messages, runs, steps, events, steering notes | `ariadne/durable.py`, `.ariadne/ariadne.db` |
| Specs | What a definition says, validation, flow templates, triggers | `ariadne/spec.py` |
| Orchestrator | One turn with the local model: verbs as tools, read-only files and web search, nothing that writes | `ariadne/orchestrate.py` |
| Engine | Sweeps schedules, runs queued runs step by step: lease, worker, jobs, checks, retries, park, cancel | `ariadne/engine.py` |
| Daemon | The one background process per machine; detached, so a closed terminal never kills a run | `ariadne/daemon.py` |
| Broker | The only thing that loads or unloads models; starts the model server on demand | `ariadne/broker.py`, `.ariadne/machine.db` |
| MCP servers for workers | memory, jobs, web, git, browser, data, office, ci, rag, diagram, image, export, text | `ariadne/*_mcp.py`, `flows/mcp_servers.yaml` |
| Watchdog | Samples RAM, VRAM and server health; never unloads under a lease holder | `ariadne/watchdog.py` |
