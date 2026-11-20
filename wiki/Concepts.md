# Concepts

| Term | Meaning |
|---|---|
| **Task** | One brief. It has a flow, an explicit model, a workspace, a session, gates and a status. |
| **Session** | A durable workstream: the chain of tasks for one repo or project. Tasks in one session share memory and history. |
| **Flow** | The declared procedure for a kind of work: `flow.yaml` + `FLOW.md` + skills + gates. The unit that replaces a bot. |
| **Backbrief** | The plan as a document: MISSION / STEPS with a model per step / CHECKS / RISKS / QUESTIONS, then the sign-off row. |
| **Gate** | How done is checked: a shell command that must exit 0, or a reviewer verdict. Gates decide, not the model's opinion. |
| **Run** | One agent invocation on one phase (plan, execute, checkpoint, review). Bounded by turns and a time budget. |
| **Segment / checkpoint** | A phase boundary where the model writes a handoff brief; the next phase starts fresh, seeded with it. |
| **Park** | A person pauses the task at its next step boundary to take the GPU. Resuming continues the same session. |
| **Job** | Heavy work handed to Ariadne: the model unloads, the job runs with the whole machine, the session wakes with the result. |
| **Skill** | Written advice for a flow (`skills/<flow>/<name>/SKILL.md`), read with `skill_view`. |
| **Memory** | Durable notes shared across tasks, recalled before planning and recorded after. |
| **Model index** | The device scan and the hardware-bounded shortlist; the catalog is filtered by it, deterministically. |
