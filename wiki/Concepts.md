# Concepts

| Term | Meaning |
|---|---|
| **Session** | The host. A durable context a person lives in: a name, a workspace, and defaults for flow and model. One session hosts many tasks. It has no execution of its own and no QA gate of its own; memory and handoff carry between its tasks. |
| **Task** | The drill. Defined first (brief → backbrief → sign-off), then executed step by step by the worker, gated per task, reported per step. The durable unit that runs, retries, and finishes. Its status always comes from `present.py::STATUS`. |
| **Busy gate** | One model, one thing. When a live worker owns a task in planning or executing and the orchestrator is not resident, the machine belongs to that task. New sessions and new tasks are refused; the only way to free the machine is Stop, which parks the task so the worker can listen again. |
| **Resident flag** | `orchestrator_resident`. When on, the busy gate is lifted and the planner and worker may co-reside. The default is off: the defining model sleeps after sign-off (the GPU handoff) and the worker runs alone. |
| **Flow** | The declared procedure for a kind of work: `flow.yaml` + `FLOW.md` + skills + gates. The unit that replaces a bot. |
| **Backbrief** | The plan as a document: MISSION / STEPS with a model per step / CHECKS / RISKS / QUESTIONS, then the sign-off row. |
| **Gate** | How done is checked: a shell command that must exit 0, or a reviewer verdict. Gates decide, not the model's opinion. |
| **Run** | One agent invocation on one phase (plan, execute, checkpoint, review). Bounded by turns and a time budget. |
| **Segment / checkpoint** | A phase boundary where the model writes a handoff brief; the next phase starts fresh, seeded with it. |
| **Park** | A person pauses the task at its next step boundary to take the GPU. Resuming continues the same session. |
| **Job** | Heavy work handed to Ariadne: the model unloads, the job runs with the whole machine, the session wakes with the result. |
| **Skill** | Written advice for a flow (`skills/<flow>/<name>/SKILL.md`), read with `skill_view`. |
| **Memory** | Durable notes shared across tasks in a session, recalled before planning and recorded after. |
| **Model index** | The device scan and the hardware-bounded shortlist; the catalog is filtered by it, deterministically. |

## Two surfaces, one rulebook

| Surface | Contract |
|---|---|
| **Direct** (console, terminal, chat) | The home. A session with current and past tasks, a conversation that continues across them, no "one task at a time" ceiling. |
| **MCP** (a foreign agent, e.g. Claude) | One task at a time. A connection may create a disposable session to define the durable task; the task then executes step by step and each step is reported back over MCP. The connection never lives in a session; it drives tasks. |

Both surfaces share one rulebook (`service.py`) and one document (`present.py`).
