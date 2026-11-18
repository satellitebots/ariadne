# Design decisions

The rules Ariadne is built on, and why. Change these only on purpose.

## Non-negotiables

| Decision | Why |
|---|---|
| **Hermes stays stock.** `upstream/` is a pinned submodule, never edited. Ariadne adds config, plugins, MCP servers, skills and a branding overlay. | Upgrades stay possible. A contract test fails loudly when Hermes moves something Ariadne depends on. |
| **Local models only.** Tools may use the internet; models never leave the machine. | Privacy and cost: the point of the project. |
| **Gates before work.** No gates, no start. | "Done" has to be checkable, or a small model will declare victory. |
| **Read-only planning, human sign-off.** | Nothing changes until you have seen the plan and the model per step. |
| **Deliberate pauses only.** Nothing interrupts a task on its own; you park it, or a login pauses it. | Losing half-done work is worse than waiting. |
| **Models write, Ariadne runs.** Heavy work is a job, run with the model unloaded. | One machine cannot hold the model and the work at once. |
| **Models never handle credentials.** Logins go to the person in debug mode. | Safety; nothing to leak. |
| **Stopping is explicit.** Detached processes, stopped from the watch window or `ariadne stop`. | A dropped terminal or remote session must not kill a task. |

## Defaults that may change

| Default | Reasoning | Revisit when |
|---|---|---|
| MoE models for planning and steps | Several times faster on 8 GB | Bigger GPU |
| `max` = 100% GPU, 80% RAM | The 90% RAM crash | More RAM, or the load moves to servers |
| QA: 10 rounds, stop after 2 without progress | Bounded cost | Gates get more reliable |
| Isolated browser by default | No logins unless asked | |
| Desktop validated last | Terminal and MCP are the main paths | After the coding flow is stable |

## Out of scope for now

- Spreading load across the two home servers (one has 64 GB RAM and no GPU).
- The Slack channel.
- One Python environment per workspace, shared by the worker's terminal and the gate commands.
