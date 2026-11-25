# Concepts

| Term | Meaning |
|---|---|
| **Flow** | A task template: `flows/<name>/template.yaml` (parameters to ask for, steps, gates, default trigger) plus the tools and models the flow allows. investigation, coding, design, content. |
| **Draft** | A task definition being shaped by you and the orchestrator. It lists what is still missing; you can edit its YAML directly. |
| **Task** | A signed definition with a name. Every edit signs a new **version**; a version never changes. |
| **Step** | One unit of work in a task: an instruction, the tools it may use, the files it must leave (`outputs`), and how it is checked (`gate`: a command, or a read-only reviewer). Steps hand over through files. |
| **Trigger** | When a task runs: `manual`, `now`, `at <time>`, or `cron` with a time zone. A missed schedule runs once on wake. |
| **Run** | One execution of one version: queued, waiting (for the machine), running, parked, then done, failed, timed out, cancelled, or needs you. |
| **Orchestrator** | The local model that talks with you and produces drafts, and manages runs on request. It never does the work. Over MCP, an outside agent can take its place (`define`). |
| **Worker** | One headless Hermes run for one step, with only that step's tools. |
| **Job** | Heavy work a worker writes as a script and hands over (`submit_job`). The models are unloaded while it runs; the worker is woken with the result. |
| **Broker** | The one owner of the model server. One **lease**, one holder (orchestrator, worker or job), a visible queue. |
| **Park / steer / resume** | Park stops a running step at its next boundary and frees the machine. Steer leaves a note for the next step. Resume continues the same step, with the notes. |
| **Debug mode** | The workers' browser attaches to your own Chrome and its sign-ins, for a step that needs a login. |
