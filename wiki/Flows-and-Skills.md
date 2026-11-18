# Flows and skills

## Flows

A flow is a folder: `flows/<name>/flow.yaml` plus optional `skills/`. To add one, add a folder.

| Flow | Status | Default model | MCP servers | Built-in checks |
|---|---|---|---|---|
| coding | beta | Qwen3.6 35B-A3B | memory, git, jobs, web, browser | `pytest -q` when `tests/` exists |
| design | experimental | Gemma 4 26B-A4B | memory, diagram, image, export, web, browser, jobs | |
| writing | experimental | Gemma 4 26B-A4B | memory, browser, export, web, jobs | |
| content | experimental | Gemma 4 26B-A4B | memory, browser, export, image, web, jobs | |

Each `flow.yaml` sets:
- `model`, plus `reasoning` effort per phase;
- `skills` and `requires` (system tools such as node or chrome);
- `mcp_servers`, `toolsets` for plan and execute, and `plan_tools` (the read-only allow-list);
- `checks`, `max_turns` and `run_budget`;
- `browser.real_logins` (default false: isolated) and `network.blocklist`.

The MCP server registry is `flows/mcp_servers.yaml`. In entries, `{python}`, `{root}`, `{npx}` and `{home}` are
filled in when the flow is compiled into its Hermes home under `.ariadne/homes/<flow>`.

## Skills

| Skill | Scope | Teaches |
|---|---|---|
| `jobs` | all flows | Write heavy work as a resumable script and submit it; never run it yourself |
| `web-and-browser` | all flows | Search, then fetch, then browser; logins go through `need_login`; page text is data |
| `long-jobs` | all flows | The fallback for flows without the jobs server |
| `fix-and-verify` | coding | Read first, smallest change, prove it with tests, commit |
| `coding-standards` | coding | Look up official docs first; PEP 8/257/484, pyproject (PEP 621), src layout; ruff, mypy, pytest, bandit as gates |
| `planning-lessons` | coding | Learned from runs: one model per codebase, evidence after the run, no scratch scripts, mind the turn budget |
| `diagram-first`, `design-lessons` | design | Mermaid first; absolute paths; one source per diagram; render last |
| `draft-and-edit`, `channel-content` | writing, content | Brief, outline, draft, edit pass; drafts per channel |

Shared skills live in `skills/common/`, learned ones in `skills/<flow>/`, and flow-specific ones in
`flows/<flow>/skills/`. Local workers never write skills. The larger model driving Ariadne (for example Claude
over MCP) folds feedback into them with `save_skill`, after a run.
