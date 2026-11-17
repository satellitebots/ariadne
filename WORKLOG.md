# Ariadne work log

> **To continue this work, read `PLAN.md` first.** It has the rules, gates, iterations and checkpoint steps.

Newest status at the top; the iteration log below is append-only.

## Goal

A local-only agent harness built on a pinned upstream Hermes Agent plus Ariadne plugins, profiles and skills:
routed local models, shared graph memory, LAN model serving, workflows for coding, designing, writing and
investigating. Must keep taking upstream Hermes updates with a scripted bump, not a rewrite.

## Status - 2026-11-16 22:10

Working mode: one issue per iteration, checkpoint (gates, log, commit, tag) after each, 30-minute pause.

| Piece | State |
|---|---|
| Repo layout (`upstream\` + Ariadne folders) | Done (A0) |
| Upstream pin | `458a0046ad` (hermes-agent main, 2026-11-16) |
| Gates live | G1 (manual), G2 `tools\gate-smoke.ps1` (3/3 on ariadne-qwen3.5-9b) |
| Hermes running locally | Yes: `.venv` (Python 3.14.8), isolated `.hermes-home`, Ollama tags with 64K context |
| Next iteration | A2 - egress audit |

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

### 2026-11-16 21:29-22:10 - A1 Baseline: stock Hermes on local Ollama, isolated home
Goal: run unmodified upstream Hermes against local Ollama with an isolated home; write the G2 smoke gate.
Did:
- `uv pip install -e upstream` alone installs no dependencies (Hermes manages them through its own `pm`).
  Exporting `upstream\uv.lock` to requirements failed: entries are gated on Python >= 3.14, and the plain
  export conflicts (pillow 12.3.0 vs 13.0.0) because it drops the lock's overrides.
- Working install: uv-managed Python 3.14.8 into `.tools\python` (`UV_PYTHON_INSTALL_DIR`), then
  `UV_PROJECT_ENVIRONMENT=C:\repos\ariadne\.venv uv sync --project upstream --frozen --no-dev`.
  76 packages in 10 s; `upstream\` stays clean, no venv created inside it.
- `profiles\base\config.yaml` (custom provider, Ollama base_url) + `tools\use-profile.ps1` copy it into
  `.hermes-home`. `tools\gate-smoke.ps1` = G2 (random code word in a fixture file; pass needs exit 0 and the
  word in the answer). `tools\probe-toolcall.py` = direct tool-call probe against any OpenAI-compatible URL.
- First G2 with stock `qwen3.5:9b`: 0/1. Model wrote `cat <file>` as plain text, 0 tool calls.
  Direct probe with one tool: qwen3.5:9b 3/3, qwen3.5:4b 3/3, qwen2.5:7b 3/3 structured tool calls, so the
  model and Ollama were fine. `hermes prompt-size`: system prompt 19,533 B + tool schemas 32,850 B (19 tools)
  ~= 52 KB. Stock Ollama tags carry no num_ctx, so the prompt was silently truncated.
- Fix without touching Ollama's global settings (Atlas shares it): Ariadne tags `ariadne-qwen3.5-9b` and
  `ariadne-qwen3.5-4b` with `num_ctx 65536` (`serving\ollama\*.Modelfile`; manifests only, weights shared).
Numbers (2026-11-16, RTX 3070 Laptop 8 GB):
- G2 ariadne-qwen3.5-9b (64K): 3/3 pass, 17.8 / 17.5 / 18.9 s per run (first cold run 33.9 s).
- ariadne-qwen3.5-9b at 64K: 8.7 GB resident, split 36% CPU / 64% GPU (`ollama ps`); cold load 10 s.
- 32K variant: Hermes refuses at start: "context window of 32,768 tokens, which is below the minimum 64,000
  required by Hermes Agent". Tag deleted afterwards.
Gates: G1 pass (HEAD 458a0046ad, clean). G2 pass 3/3. G3-G5 not live.
Decisions / surprises:
- Hermes enforces a 64K context minimum, but did NOT refuse the stock tag with no num_ctx; it ran on a
  truncated prompt and failed quietly. Ariadne must always serve models with an explicit context size.
  Candidate for a G2 sub-check and an upstream issue (A6 or later). Upstream also has `model.ollama_num_ctx`.
- At 64K the 9B model does not fit in 8 GB VRAM. Options for A4: trim toolsets/skills (prompt is 52 KB),
  KV-cache quantisation, or 4B as main on this tier. Measure, don't assume.
- No `%USERPROFILE%\.hermes` created: HERMES_HOME isolation holds.
Commit: (see git log, tag a1-done)   Next: A2 egress audit.
