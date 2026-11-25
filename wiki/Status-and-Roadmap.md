# Status and roadmap

*As of 25 Nov 2026.* The redesign (`docs/DESIGN.md`, 24 Nov) is built; the old task model is removed.

## Built

| Piece | Where | Proof |
|---|---|---|
| Broker: one lease, a queue, handoff at boundaries, same-weights switch, server started on demand | `broker.py` | `test_broker.py` |
| Durable tasks: specs, templates, signed versions, drafts, runs, triggers | `spec.py`, `durable.py` | `test_durable.py` |
| One verb registry; MCP, HTTP and terminal generated from it | `verbs.py`, `front_mcp.py`, `server/app.py`, `__main__.py` | `test_surfaces.py` |
| Engine: steps as Hermes workers, files as handover, checks and retries, jobs, park/steer/resume, cancel, scheduler | `engine.py`, `daemon.py` | `test_engine.py` |
| Orchestrator: local, verbs as tools, nothing that writes | `orchestrate.py` | `test_orchestrate.py` |
| Console rebuilt on the verbs | `ui/` | screenshots in the session notes |
| First real orchestrator turn | 25 Nov: filled the investigation template from one message, ready to sign | `.ariadne` events |

## In progress

- **The first real run:** `googl-daily` (investigation, Qwen3.6 35B-A3B), defined in the orchestrator, signed, run.

## Next

1. Schedule `googl-daily` and let a scheduled run happen; write it up as a case study.
2. Trim what a step loads: each worker currently opens with about 12K tokens of tool and skill descriptions.
3. Rebuild coding, design and content as templates.
4. Start the background process at login, so schedules fire after a reboot.
5. Redo the RAG build on the new engine.

## Parked

In `docs/BACKLOG.md` ("Parked ideas"): the two home servers, compression and instruction-decay telemetry, default
quality gates, one Python environment per workspace, Slack.
