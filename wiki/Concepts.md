# Concepts

These are the words used everywhere else in this wiki, roughly in the order you meet them.

| Term | Meaning |
|---|---|
| **Task** | One piece of work: text, a workspace (a folder or repo), a flow, check gates. It has an id like `t1118-051537-e531`. |
| **Flow** | A kind of work: `coding`, `design`, `writing`, `content`. A flow fixes the default model, tools, MCP servers, skills, checks and budgets. See [Flows and skills](Flows-and-Skills.md). |
| **Check gates** | How we know a task is done, end to end. *Command gates* (`run: pytest -q`) must exit 0. *Review gates* ("README documents every command") are judged by a separate read-only reviewer that must cite evidence. |
| **Brief / backbrief** | The brief is what you give. The backbrief is the plan the model sends back: mission, numbered steps, a model per step, which step passes which gate, and the risks. |
| **Sign-off** | Your approve, revise or cancel on the backbrief. Approving locks the plan and each step's model. |
| **QA loop** | After execution the gates run. Failures go back to the worker with the reasons, up to 10 rounds. The loop stops early after two rounds in a row with no progress. |
| **Session** | A workstream: a chain of tasks and the conversation between them. One per desktop or terminal chat, or named with `--session`. |
| **Segment / checkpoint** | A session is split into segments, one per phase on one model. At each checkpoint (plan approved, step group done, QA done) the model writes a handoff brief and the next segment starts from it, so contexts stay small. |
| **Job** | Heavy work written by the model as a script and run by Ariadne with the model unloaded. When it finishes, the model is woken in the same conversation with the result. See [Jobs](Jobs.md). |
| **Park** | A deliberate pause of the running task at its next step boundary, so you can have the model. It is never automatic: you park, or a step calls `need_login`. See [Parking and KV cache](Parking-and-KV-Cache.md). |
| **KV cache parking** | Saving a model's working memory (KV cache) to disk under session, step and model. When that session resumes on that model, it is restored instead of re-reading the whole conversation. |
| **Resource profile** | How much of the machine the models may take: `max`, `shared` or `light`. See [Models and resources](Models-and-Resources.md). |
| **Skill** | A `SKILL.md` of specific, imperative guidance that the models load: shared (`skills/common`), per flow, or learned from earlier runs (`planning-lessons`). |
| **Debug mode** | The browser tools attach to *your* running Chrome and its sign-ins, instead of a clean isolated profile. You turn it on when a step needs a login. See [Web, browser and logins](Web-and-Browser.md). |
| **Worker** | The background process that routes, plans, executes and QAs tasks. It runs detached from any terminal. |
| **Model server** | llama-swap in front of llama.cpp, serving the catalog models on `127.0.0.1:8090`. |
