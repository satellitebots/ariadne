# Ariadne work log

> **To continue this work, read `PLAN.md` first.** It has the rules, gates, iterations and checkpoint steps.

Newest status at the top; the iteration log below is append-only.

## Goal

A local-only agent harness built on a pinned upstream Hermes Agent plus Ariadne plugins, profiles and skills:
routed local models, shared graph memory, LAN model serving, workflows for coding, designing, writing and
investigating. Must keep taking upstream Hermes updates with a scripted bump, not a rewrite.

## Status - 2026-11-16 21:00

Working mode: one issue per iteration, checkpoint (gates, log, commit, tag) after each, 30-minute pause.

| Piece | State |
|---|---|
| Repo layout (`upstream\` + Ariadne folders) | Done (A0) |
| Upstream pin | `458a0046ad` (hermes-agent main, 2026-11-16) |
| Gates live | G1 only (manual); G2-G5 not written yet |
| Hermes running locally | Not yet (A1) |
| Next iteration | A1 - stock Hermes on local Ollama, isolated home |

## Iteration log

### 2026-11-16 20:30-21:00 - A0 Scaffold
Goal: set up the repo so Ariadne can extend Hermes without forking it.
Did:
- Cloned NousResearch/hermes-agent (main) and moved it to `upstream\` (own .git; remote renamed `upstream`).
- Created Ariadne repo around it; wrote PLAN.md, WORKLOG.md, README.md, hermes.lock, .gitignore.
- Surveyed upstream extension points (from upstream docs `user-guide/features/plugins.md` and
  `developer-guide/plugins/index.md`): memory-provider plugins, context-engine plugins, model-provider
  plugins, delegation providers, lifecycle hooks, slash/CLI commands, MCP via config, skill taps.
  Upstream's native plugin compatibility contract: documented PluginContext methods are not removed or
  renamed, new params get defaults, provider interfaces grow through defaults.
- Confirmed `HERMES_HOME` env var is honoured (`hermes_constants.py`) - used for the isolated home.
- Confirmed local Ollama works as `provider: custom`, `base_url: http://localhost:11434/v1`
  (upstream `guides/local-ollama-setup.md`).
- Checked machine: RTX 3070 Laptop 8 GB (1.7 GB in use at check), 32 GB RAM, Python 3.13.5, uv 0.13.1,
  127 GB free on C:, no llama-server or llama-swap installed, no `%USERPROFILE%\.hermes`.
Numbers: upstream checkout 26,196 files.
Gates: G1 pass (HEAD 458a0046ad, status clean). G2-G5 not live.
Decisions / surprises:
- `plugins\model-providers\router` upstream is Ramp's hosted router, not a local router - not usable.
- 8 GB VRAM rules out 27B-class models on GPU; start with qwen3.5:9b main, qwen3.5:4b router.
Commit: (see git log, tag a0-done)   Next: A1.
