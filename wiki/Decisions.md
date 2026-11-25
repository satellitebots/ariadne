# Decisions

The current ones; `docs/DESIGN.md` has the reasoning in full.

| Decision | Why |
|---|---|
| **One front, generated** | MCP, HTTP and the chat are generated from `verbs.VERBS`, and a test checks they match. A front cannot drift or grow a feature of its own. |
| **The orchestrator defines, never works** | It has no write, patch or terminal tool. Its only output is a draft; doing is the workers' job. |
| **The orchestrator is local; MCP is the bypass** | It runs on this machine and shares the GPU. An outside agent over MCP can hand in a whole definition (`define`), so the local model never loads. |
| **A task is a signed, versioned definition; a run executes one version** | Scheduling needs a definition that outlives its runs. Editing makes a new version to sign; runs in flight finish on theirs. |
| **One worker per step, fresh context, files as the handover** | Small models do better with small contexts and a single job; a step's files are the evidence a check can read. |
| **One owner of the machine** | Every November failure came from models loading behind each other's backs. Only the broker loads or unloads; handoffs happen at step boundaries. |
| **Nothing interrupts a run on its own** | A running step keeps the machine until its boundary. Park is a person's act; steering is park, steer, resume. |
| **The orchestrator uses the workers' weights when it can** | Then a handoff is a cache switch, not a 22 GB reload. |
| **Jobs get the whole machine** | Heavy work in the model's terminal held the GPU and timed out. A job runs with every model unloaded. |
| **Flows are templates, not bots** | A small orchestrator cannot invent coordination reliably; a template carries the steps, tools and gates, and the orchestrator fills it in. |
| **Hermes stays stock** | `vendor/hermes` is pinned and never edited (overlay for anything that must differ). Only its headless worker is used: no gateway, persona or messaging. |
| **Local-only inference** | `local_only` refuses any model endpoint that is not loopback, LAN or allowlisted, and any API key. Tools may use the internet. |
| **Logins are the person's** | Workers never type credentials; `need_login` pauses the run for you to sign in (debug mode). |
