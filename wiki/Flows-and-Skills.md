# Flows and skills

A **flow** is the unit of work: a folder under `flows/` that says how one kind of task is done. It replaces the bot concept - there is no persona and no soul file, only a declared procedure a person signs off.

## The four approved flows

The closed set is defined in `flows/flows.yaml`:

| Flow | Focus |
|---|---|
| `coding` | Read/edit files, terminal, git, tests, CI, RAG builds, profiling, media pipelines. |
| `design` | Markdown + Mermaid, diagram sets (C4/ER/sequence), SVG+PNG, draw.io/diagrams.net, ADRs, exported packs. |
| `investigation` | Web search/fetch, repo reading, debug browser, csv/xlsx/sqlite, citation trails, multi-source triangulation. |
| `content` | Reference-based generation, citation gates, fact-check pass, image generation, house style as a skill. |

**`writing` is retired.** It is not in the closed set and `submit` refuses it. Content that was once "writing" now lives in `content` with its citation and fact-check machinery.

## A flow folder

```
flows/coding/
  flow.yaml     the declaration
  FLOW.md       the coordination, injected into the plan prompt
  skills/       flow-local skills (fix-and-verify, coding-standards, ...)
```

`flow.yaml` keys: `name`, `description`, `when`, `model`, `execute_model`, `reasoning`, `status`, `skills`, `mcp_servers`, `toolsets` (plan/execute), `plan_tools` (what the read-only plan may call), `checks` (shell gates), `requires`, `browser`, `max_turns`, `max_iterations`, `run_budget`, `task_budget`. An unknown key is a typo and is refused at load.

## Skills

- `skills/common/*` applies to every flow; `skills/<flow>/*` to that one. The flow's copy wins on a name clash.
- The plan prompt lists name and description; `skill_view` returns the body, so a run can follow a skill instead of only knowing it exists.
- Skills are written by the larger models that drive Ariadne over MCP (`save_skill`), or contributed as a pull request. They are versioned in the repo.

## MCP servers a flow may name

`memory`, `jobs`, `web`, `git`, `browser`, `vscode`, `export`, `image`, `diagram`, `text`, `data`, `office`, `ci`, `rag`. `flows/tools.yaml` is the approved set; naming a server that is not declared in `flows/mcp_servers.yaml` is refused at load.

## Read-only plans

`plan_tools` is the allowlist the plan phase is given. The loop offers only those tools - there is no prompt-level promise to break - and a read-only phase refuses a write tool at dispatch.

## Gates and retries

- `Flow.max_iterations` is 5 = one run plus at most four retries. The no-progress rule stops earlier.
- A template carries the steps and gates; the orchestrator fills in its parameters and may sharpen a gate before you sign (`flows/<name>/template.yaml`; investigation is the first).
