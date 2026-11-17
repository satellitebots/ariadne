# Ariadne work log

> **To continue this work, read `PLAN.md` first.** It has the rules, gates, iterations and checkpoint steps.

Newest status at the top; the iteration log below is append-only.

## Goal

A local-only agent harness built on a pinned upstream Hermes Agent plus Ariadne plugins, profiles and skills:
routed local models, shared graph memory, LAN model serving, workflows for coding, designing, writing and
investigating. Must keep taking upstream Hermes updates with a scripted bump, not a rewrite.

## Status - 2026-11-16 23:10

Working mode: one issue per iteration, checkpoint (gates, log, commit, tag) after each, 30-minute pause.

| Piece | State |
|---|---|
| Repo layout (`upstream\` + Ariadne folders) | Done (A0) |
| Upstream pin | `458a0046ad` (hermes-agent main, 2026-11-16) |
| Gates live | G1 (manual), G2 `tools\gate-smoke.ps1`, G3 `tools\gate-egress.ps1` (0 external hosts with `profiles\base`), G4 `hermes plugins doctor`, G5 `pytest plugins` |
| Hermes running locally | Yes: `.venv` (Python 3.14.8), isolated `.hermes-home`, Ollama tags with 64K context |
| Offline | Config closes all observed egress (3 hosts, one catalog refresh); see A2 table |
| Next iteration | A3 in progress: plugin + G4/G5 done; G2/G3 runs wait for the GPU (Atlas eval) |

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

### 2026-11-16 22:09-22:35 - A2 Egress audit
Goal: find every outbound host Hermes contacts during a local task; write G3.
Did:
- Static scan of upstream (2,334 .py files, tests excluded): no global offline switch. Network-capable
  defaults found in `hermes_cli/config_defaults.py`: `updates.check: true`, `model_catalog.enabled: true`
  (hermes-agent.nousresearch.com), `models_dev` (models.dev/api.json), `plugins.auto_update_check_hours: 24`,
  `telemetry.shared_metrics` (already off by default).
- Measurement: `tools\egress_hook.py`, loaded by `.venv\Lib\site-packages\ariadne_egress.pth`
  (`tools\install-egress-hook.ps1`), logs every getaddrinfo, socket connect and subprocess spawn with pid
  and the last 6 Hermes frames. Inert unless `ARIADNE_EGRESS_LOG` is set. It runs in every venv process,
  which matters: the CLI auto-starts a background `gateway run --idle-exit` that does the model calls. The
  first in-process-only probe missed it and wrongly reported zero egress.
- `tools\egress_report.py` classifies endpoints (loopback / RFC 1918 / .lan = local) and flags networked
  spawns. `tools\gate-egress.ps1` = G3: stops any Ariadne gateway, runs the smoke task with the hook, waits
  20 s for background refreshes, stops the gateway, fails on any external host OR a failed task.
Numbers (smoke task, ariadne-qwen3.5-9b, n=1 per row unless noted):

| Run | External endpoints | Task | Time |
|---|---|---|---|
| Stock config (upstream defaults) | 6 (3 hosts) | ok | 43.7 s |
| Stock config + dead HTTPS_PROXY (127.0.0.1:9) | 0 (all 3 hosts went to the dead proxy) | ok | 30.5 s |
| Offline config (`profiles\base`), n=2 | 0, 0 | ok, ok | 43.1 s, 43.2 s |

Outbound hosts with stock config (all from one background catalog refresh in the CLI process):

| Host | Code | Needed? | Turned off by |
|---|---|---|---|
| hermes-agent.nousresearch.com:443 | `hermes_cli/model_catalog.py:129` (get_catalog <- refresh_catalogs) | No | `model_catalog.enabled: false` |
| nousresearch.github.io:443 | same fetch, fallback URL | No | same |
| openrouter.ai:443 (`/api/v1/models`) | `hermes_cli/models.py` fetch_openrouter_models(force_refresh) <- `model_catalog.py:306` | No | same (refresh_catalogs returns early) |

Local endpoints seen: Ollama (127.0.0.1 / ::1 / localhost :11434), CLI<->gateway loopback ports, relay
runtime loopback port. Spawns: git (29, all local read-only: rev-parse, status, describe, config),
Git Bash for the terminal tool, `schtasks /Query` x2 (read-only check for a `Hermes_Gateway_*` autostart
task; none exists), `pip --version`, python. No networked spawn.
Gates: G1 pass. G2 pass (1/1 on the offline profile). G3 pass with offline config, n=2 (live from now).
Decisions / surprises:
- Config alone closes all observed egress. Offline switches now live in `profiles\base\config.yaml`
  with the reason for each. A3 becomes defense in depth (a guard for hosts config can't name), not the fix.
- Hermes's HTTP clients honour HTTPS_PROXY: a dead local proxy blocked all 3 hosts and the task still
  worked. Cheap second layer for A3.
- models.dev was not fetched in these runs (custom endpoint resolves context via Ollama /api/show).
  It stays on the watch list: a different provider path could trigger it.
- Incident: one of my tool calls returned no output but kept running detached; I started a second gate
  run with the same tag and the two runs killed each other's gateway ("Gateway disconnected", Hermes
  logged the gateway as exited uncleanly). Fix: a machine-wide mutex (`Global\AriadneGate`) in both gate
  scripts; overlapping runs now refuse with exit 2. G3 also now fails when the task fails.
- Hook limitation: raw-IP connects made by asyncio's proactor bypass socket.connect; name lookups are
  still caught. Acceptable for an audit; the A3 guard should block at a lower level.
Commit: (see git log, tag a2-done)   Next: A3 offline guard.

### 2026-11-16 22:55-23:10 - A3 Offline guard (part 1 of 2: CPU-side; interim checkpoint)
Goal: defense in depth so a future upstream fetch is blocked and logged even if config misses it.
State at start: G1 pass. G2/G3 NOT run: Atlas eval `p1c-q35-4b` holds the GPU (100% util, item 18/300 at
~14 s/item at 22:58, ~65 min left). Rule 9: one GPU job at a time, so model runs wait.
Did (from upstream docs `developer-guide/plugins/index.md`, `user-guide/features/hooks.md`,
`user-guide/features/plugins.md`):
- Plugins are opt-in (`plugins.enabled`), discovered in `<HERMES_HOME>/plugins/<name>/` (plugin.yaml +
  `register(ctx)`). `pre_tool_call` is a policy hook: `{"action": "block", "message": ...}` wins over
  approve. Toolsets can be removed in config with `agent.disabled_toolsets`.
- Layer 1, config: `agent.disabled_toolsets: [web, browser, browser-use, browser-cdp]` in `profiles\base`.
- Layer 2, `plugins\offline_guard` (Ariadne plugin, upstream untouched):
  - `guard.py`: process-wide wrap of socket.getaddrinfo, socket.connect/connect_ex and asyncio
    `sock_connect` (base, proactor, selector loops; closes the raw-IP asyncio gap the A2 hook had).
    Non-local -> PermissionError (clients see a normal network error) + JSONL record with frames in
    `<HERMES_HOME>/logs/offline_guard.jsonl`. Local = loopback, RFC 1918/ULA, link-local, single-label
    names, .lan/.local/.home.arpa/.internal, `ARIADNE_ALLOW_HOSTS`. Modes via `ARIADNE_OFFLINE_GUARD`:
    enforce (default) | log | off.
  - `policy.py` (`pre_tool_call`): blocks web/browser tools; any argument URL with a non-local host;
    networked commands (curl/wget/Invoke-WebRequest, pip/npm install, npx, uvx, git clone/fetch/pull/push,
    ssh/scp, package managers) unless every URL they name is local. Covers children the socket guard
    cannot see (terminal tool spawning curl).
- `tools\use-profile.ps1` now syncs `plugins\<name>\` (without tests) into `.hermes-home\plugins\`.
- `profiles\guard-proof`: base minus the A2 catalog/update switches, guard on. Test-only.
- `tools\gate-egress.ps1 -ExpectGuardBlocks`: also requires >= 1 guard block, so the run proves the guard
  (not config) stopped real Hermes egress. Rewritten whole after an in-place edit corrupted it (a `$_` in
  a PowerShell -replace replacement string expands to the whole input); restored from a2-done first.
- pytest 9.1.1 (version pinned in upstream uv.lock) installed into `.venv` for G5.
Numbers:
- G5 `python -m pytest plugins -q`: 40 passed in 0.36 s (19 host classifications, external DNS / raw-IP
  socket / urllib / raw-IP asyncio all refused, local TCP round trip allowed, block logged, 14 tool
  policy cases).
- G4 `hermes plugins doctor plugins\offline_guard --ci`: OK (discovery, manifest, import, registration;
  0 tools, 1 hook). `hermes plugins list`: offline_guard enabled, source user.
Gates: G1 pass. G4 pass (live). G5 pass (live). G2, G3, G3 guard-proof: pending GPU.
Remaining for A3: G2; G3 on base; G3 on guard-proof with -ExpectGuardBlocks (expected: 0 external,
>= 1 guard block from the catalog refresh, task ok); dead-proxy decision; WORKLOG; tag a3-done.
Commit: interim (see git log)   Next: finish A3 when the GPU is free.
