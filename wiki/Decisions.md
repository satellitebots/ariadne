# Decisions

| Decision | Why |
|---|---|
| **Local inference only** | A cloud provider is refused by `local_only` at every command that can start a model. A localhost/LAN Ollama server is allowed through the serving registry; nothing else is. |
| **No messaging** | Telegram, Slack, Discord and the bot gateway are not surfaces Ariadne has. Nothing to connect, nothing to configure. |
| **Flows replace bots** | A Hermes bot is a persona with a soul file. Ariadne's unit is a flow: `flow.yaml` + `FLOW.md` + skills + gates, declaring model, toolsets, MCP servers, plan allowlist and how done is checked. A person signs off a plan, not a personality. |
| **Hermes is the worker backend** | The loop, tools, skills, MCP client, compression and provider handling are Hermes's. Reimplementing them would be a rewrite with no upside. |
| **Overlay, not subtree, not root merge** | The submodule stays pristine and updatable; our modules live in `overlay/` and win by `sys.path` + `__path__`. No 163k-line diff in our history, no broken absolute imports. |
| **Replace only the wrong hook** | Console app, chat and MCP hosting became ours because their integration points belong to the orchestrator. Everything else stays Hermes's. |
| **Explicit choice, enforced** | A task needs an explicit flow and an explicit agent model. `service.submit` refuses otherwise, so every door refuses identically. |
| **Read-only plans at dispatch** | The plan/review/checkpoint phases are not offered write tools at all - a property of the loop, not a promise in a prompt. |
| **The gates decide** | Out of time or out of turns is not failure: the work stays and the gates decide. Two iterations with no progress stop the loop. |
| **One model on the GPU** | The worker unloads between phases; jobs run with the model unloaded and wake the same session with the result. |
| **The index is deterministic** | The shortlist is weights + a fixed overhead against VRAM and the profile's total. Hugging Face suggestions are opt-in, cached, and never edit the catalog. |
