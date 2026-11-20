# Gap analysis: why there is no simple system yet

Written 2026-11-19, after twelve backlog items were closed and the product still could not run a task without
Hermes. This document answers three questions: what actually went wrong, what is missing (with counts, not
adjectives), and what it costs to close.

## 1. What went wrong

Three failures, in order of cost.

**1. The dependency on Hermes was never written down, so it could never be removed.**
`DESIGN-RESET.md` decided Ariadne would not own an agent loop, and `FORK.md` made the pinned Hermes the runtime.
That decision was defensible. What was missing was the interface: Ariadne's dependence on Hermes lived in five
implicit places and nowhere else.

| What Ariadne depended on | Where it lived | Consequence |
|---|---|---|
| Toolset names (`file`, `terminal`, `skills`, `todo`, `search`) | an argv string in `hermes_run` | no way to know what a flow actually needs |
| MCP servers, named `mcp-<server>` | an argv convention | the four servers built in B6 are unreachable without Hermes |
| A session id | a regex over Hermes' stdout (`_SESSION_ID`) | resume is a text scrape, not a contract |
| A gateway process | `stop_gateway()` after a timeout | a kill path tied to a process we do not own |
| Task context (`ariadne_phase`, `ariadne_task`, `ariadne_workspace`) | files the jobs MCP server reads | the servers only work inside a Hermes run |

Because the contract was implicit, "done" for any item meant "works when Hermes is installed". No item could be
tested for ownership. When the decision was finally made to own the loop, the contract had to be reverse-engineered
from a command line - which is exactly the work that should have been done before B1.

**2. The queue was capability-first and platform-last.**
B1-B14 added wall-clock budgets, a watchdog, a store, four MCP servers, draw.io export, citations, an HTTP server,
chat, schedules and a doctor. Every one of them plugged into a runtime that was scheduled to be replaced (B12 was
item twelve). The four MCP servers are the clearest case: built, tested, and unreachable from Ariadne's own loop.
Twelve items were "done" on a foundation with a known expiry date. The frame should have been item one.

**3. The acceptance test was weaker than the claim.**
B12.2's drill proves brief -> plan -> sign-off -> execute -> gates with `HERMES_EXE` pointed at a path that does not
exist. That is real. But the scripted model makes exactly **one** tool call (`terminal`), and never touches an MCP
server, a skill, or the web. So the drill proves the loop, the phase split, the gates and the workspace jail - not
that a task can be done. The difference matters: a coding task names 24 tools and the runtime offers 2 of them.

## 2. What is missing, counted

The runtime is `ariadne/runtime/` - 5 files, 363 lines, 6 tools (3 read-only). The flows ask for:

| Surface | Coding | Content | Design | Investigation | Runtime today |
|---|---|---|---|---|---|
| MCP servers | 8 | 7 | 8 | 7 | **0** |
| Skills | 2 | 3 | 1 | 1 | 0 (index only, in the plan prompt) |
| Plan tools named | 24 | 14 | 15 | 14 | **2** (`read_file`, `search_files`) |
| Execute toolsets | 5 | 4 | 4 | 5 | 2 (`file`, `terminal`, partly) |

Distinct across all flows: 12 MCP servers, 7 skills, and 22 of the 24 tools the coding plan names. The 22 missing
split as: browser 7, VS Code 6, skills 2, web 2, git 4, memory 1.

What the worker does around the runner is complete and should not be rebuilt: planning, the backbrief, sign-off,
gates, retries, per-link model chains, job cycles, wall-clock expiry, the store, the server and the console. The gap
is entirely the runner's capability surface, plus the hooks the worker expects a runner to have.

## 3. What it costs

| Item | Work | Size |
|---|---|---|
| B12.3 MCP client in the runtime | spawn servers from `mcp_servers.yaml` over stdio, namespace `mcp__<server>__<tool>`, per-flow filtering, lifecycle per run | ~150 lines + test |
| B12.4 skills as tools | `skills_list` / `skill_view` over `ariadne.skills` | ~50 lines + test |
| B12.5 web search | `web_search` over `ddgs` (already installed); `web_fetch` already exists in `web_mcp` | ~40 lines + test |
| B12.6 parity hooks | park, KV registration, jobs wake-up, per-run log artifact, `todo`, context trimming | ~270 lines + tests |
| B12.7 flip and delete | default to the runtime; delete `hermes_run`, `_clean_output`, `_kill_tree`, `_turn_end_reason`, `_latest_session`, `stop_gateway` (~134 lines, 36 references) and the `upstream/` submodule | net -134 lines |
| B12.8 chat on the runtime | `ariadne chat` currently launches `hermes chat` | ~80 lines |

Total: roughly 600 lines against ~163,000 for option one (gutting the pin), with the whole difference being code we
would have to maintain forever. **The rebuild is the cheaper option, and it is the only one that ends with a system
Ariadne owns.**

## 4. Order

The queue is in `docs/BACKLOG.md` under B12.3-B12.8. The rule that was missing the first time: an item is done only
when a test exercises it with no Hermes binary present. B12.3 comes first because twelve approved servers are already
written and tested and the runtime cannot call any of them; B12.7 comes last because flipping the default before the
surface exists would turn working Hermes tasks into broken runtime tasks.

Not a gap, and not to be rebuilt: the task store, the orchestrator loop, gates, the HTTP server, the console, memory,
the four newer MCP servers, draw.io export and citations. They are tested and they do not care which runner is under
them.
