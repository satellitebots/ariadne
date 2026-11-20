# Flows and skills

A **flow** is the unit of work: a folder under `flows/` that says how one kind of task is done. It replaces the bot
concept - there is no persona and no soul file, only a declared procedure a person signs off.

## A flow folder

```
flows/coding/
  flow.yaml     the declaration
  FLOW.md       the coordination, injected into the plan prompt
  skills/       flow-local skills (fix-and-verify, coding-standards, ...)
```

`flow.yaml` keys: `name`, `description`, `when`, `model`, `execute_model`, `reasoning`, `status`, `skills`,
`mcp_servers`, `toolsets` (plan/execute), `plan_tools` (what the read-only plan may call), `checks` (shell gates),
`requires`, `browser`, `max_turns`, `max_iterations`, `run_budget`, `task_budget`. An unknown key is a typo and is
refused at load.

The four approved flows are `coding`, `design`, `investigation` and `content` (`flows/flows.yaml` is the closed set).

## Skills

- `skills/common/*` applies to every flow; `skills/<flow>/*` to that one. The flow's copy wins on a name clash.
- The plan prompt lists name and description; `skill_view` returns the body, so a run can follow a skill instead of
  only knowing it exists.
- Skills are written by the larger models that drive Ariadne over MCP (`save_skill`), or contributed as a pull
  request. They are versioned in the repo.

## MCP servers a flow may name

`memory`, `jobs`, `web`, `git`, `browser`, `vscode`, `export`, `image`, `diagram`, `text`, `data`, `office`, `ci`,
`rag`. `flows/tools.yaml` is the approved set; naming a server that is not declared in `flows/mcp_servers.yaml` is
refused at load.

## Read-only plans

`plan_tools` is the allowlist the plan phase is given. The loop offers only those tools - there is no prompt-level
promise to break - and a read-only phase refuses a write tool at dispatch.
