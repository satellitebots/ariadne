# Ariadne work log

> **To continue this work, read `PLAN.md` first.** It has the rules, gates, iterations and checkpoint steps.

Newest status at the top; the iteration log below is append-only.

## Goal

A local-only agent harness built on a pinned upstream Hermes Agent plus Ariadne plugins, profiles and skills:
routed local models, shared graph memory, LAN model serving, workflows for coding, designing, writing and
investigating. Must keep taking upstream Hermes updates with a scripted bump, not a rewrite.

## Status - 2026-11-17 14:30

Working mode: architecture locked (Architecture doc), POC built and proven end to end; checkpoints continue.

| Piece | State |
|---|---|
| Repo | GitHub `satellitebots/ariadne` (origin, user 13:52); upstream Hermes pinned `458a0046ad`, untouched |
| Gates | G1 upstream intact, G2 smoke (2/2 llamaswap), G4 plugin doctor (ariadne_phase, offline_guard), G5 pytest 60 passed. G3 egress gate kept for the base profile only: the design no longer blocks the internet (user 13:09) |
| Models | Local only: llama-swap (coder 9B, router 4B, embed) on 127.0.0.1:8090, Ollama 4B fallback; one model on the GPU |
| Flows | `flows\coding`, `flows\writing`, `flows\content` (+ `flows\mcp_servers.yaml`); compiled to one Hermes worker home each under `.ariadne\homes` |
| Orchestrator | `ariadne\orchestrator.py`: brief -> route (router LLM) -> plan (read-only) -> backbrief -> sign-off -> execute -> checks (retry once) -> report; single worker process; off-plan goes back to the person |
| Entry points | `ariadne-tasks` MCP server (Claude / any MCP client); Hermes gateway via `profiles\ariadne` + `ariadne-tasks` skill (CLI proven; Slack needs tokens); CLI `python -m ariadne.orchestrator` |
| Shared memory | `ariadne\memory.py` (SQLite graph + FTS5) in `.ariadne\memory.db`; MCP server for workers; orchestrator records every task |
| Tools in flows | Chrome DevTools MCP (real logins by default, `browser.real_logins: false` per flow), VS Code MCP extension (JuehangQin.vscode-mcp-server 0.4.0, installed), Pandoc 3.14 export server; per-flow `network.blocklist` |
| Next | SD Turbo (needs the user's OK: > 2 GB download), Slack live (tokens), golden task gate G6, A6 upgrade drill, A7 evals (PLAN 4c) |

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

### 2026-11-17 09:50-10:10 - A3 Offline guard (part 2 of 2) - done
Goal: prove the guard on real Hermes traffic; finish A3.
GPU check 09:50: Atlas newest job `p3s8` done 09:34, no unfinished Atlas log in the last 30 min, Atlas
python idle (CPU 0). GPU at ~25% / 2.5 GB = display + idle qwen3-embedding:0.6b, not a job. Proceeded.
Did / found:
- **New egress the A2 audit missed: models.dev.** First G3 on base this morning: 0 external but 1 guard
  block, `dns models.dev:443` from the gateway (`agent/models_dev.py:364`, requests). Cause:
  `.hermes-home\models_dev_cache.json` (6.7 MB) was written 2026-11-16 21:32 during A1 (stock config,
  before any egress logging); its TTL is 4 h (`_MODELS_DEV_CACHE_TTL`), so it was fresh during A2
  (22:09-22:35) and no fetch happened. A2's "config closes all observed egress" held only for what A2
  observed. models.dev has no on/off switch, only `models_dev.url`.
  Fix (config first): `models_dev.url: http://127.0.0.1:9/models-dev-disabled.json` in `profiles\base`.
  The stale refresh now fails locally (egress log: 127.0.0.1:9 from models_dev.py:364) and Hermes serves
  the stale cache; cache file untouched. A12: ship a local models.dev snapshot.
- **Guard coverage gap: the CLI does not load plugins.** In the first guard-proof run all 4 blocks came
  from the gateway (which also made the 23 Ollama calls) and logged "offline guard active"; the CLI pid
  never did. No leak (egress hook: 0 external in both pids), but a future CLI-side fetch would be unguarded.
  Fix inside Ariadne's venv only: `tools\guard_loader.py` + `tools\install-guard-pth.ps1` write
  `.venv\Lib\site-packages\ariadne_offline_guard.pth`, which starts the guard in every venv Python process
  when `ARIADNE_GUARD_ALL_PROCS=1` (set by both gate scripts). A process-wide marker
  (`socket._ariadne_offline_guard`) stops the plugin and the loader wrapping twice; new G5 test for it.
  First .pth version was broken (`\r` in `C:\repos` became a carriage return inside an exec string and
  every venv process printed a .pth error); replaced with the egress-hook pattern within minutes.
- Loader check: without the env var, inert (marker False); with it, `getaddrinfo('example.com')` in a bare
  venv python -> PermissionError + JSONL record; localhost allowed.
Numbers (ariadne-qwen3.5-9b, RTX 3070 Laptop 8 GB):

| Run | External | Guard blocks | Task | Time |
|---|---|---|---|---|
| G2 base x3 (guard plugin on) | - | - | 3/3 | 54 (cold), 18.9, 18.4 s |
| G3 base, before models_dev fix | 0 | 1 (models.dev) | ok | 31.8 s |
| G3 base, models_dev -> loopback | 0 | 0 | ok | 41.0 s |
| G3 guard-proof (stock catalog/update/models.dev), plugin only | 0 | 4 | ok | 30.0 s |
| G3 guard-proof, plugin + all-process loader | 0 | 4 | ok | 42.7 s |
| G3 base final #1 | 0 | 0 | FAIL (answer "A5 part 1") | 28.8 s |
| G2 base x1 | - | - | 1/1 | - |
| G3 base final #2 | 0 | 0 | ok | 31.0 s |

Guard-proof blocks (both runs, gateway pid): models.dev, hermes-agent.nousresearch.com,
raw.githubusercontent.com (a catalog fallback URL A2 never saw; A2's fallback went to
nousresearch.github.io), openrouter.ai. With the loader, every socket event in both pids (CLI 1/1,
gateway 22/22) passed through guard.py.
Gates: G1 pass. G2 pass. G3 pass (base, final #2; final #1 failed on answer content only). G3
guard-proof pass. G4 pass. G5 pass (41 tests).
Decisions / surprises:
- G3 base final #1: model called read_file correctly (2.04 s, 163 chars) and then answered "A5 part 1".
  Hermes runs with cwd C:\repos\ariadne, so repo files (PLAN/WORKLOG naming A1..A12) reach the context.
  Small-model reliability issue, not a guard issue. For A7: run evals from a neutral cwd, track this rate.
- Dead local HTTPS_PROXY: not adopted now. It blocked all 3 proxy-aware calls in A2, but the guard now
  covers every Ariadne Python process and the policy covers networked commands; the proxy only adds
  proxy-aware non-Python children, and costs a NO_PROXY entry for every LAN model host (A5). Revisit in
  the A12 launcher with NO_PROXY generated from the guard allow-list. Real enforcement for children =
  OS outbound firewall rule: changes the user's system, ask first (A12).
Commit: (see git log, tag a3-done)   Next: A4 model serving on this machine.

### 2026-11-17 10:34-11:10 - A4 Model serving on this machine - done
Goal: one local URL serving coder / router / embed (vision noted), measured; make the main model fit 8 GB.
GPU check 10:34: Atlas `p4-replay` done 10:15, nothing loaded, 0% util. Gates at start: G1, G5 (41),
G4, G2 1/1, G3 (0 external, 0 blocks) pass.
Did:
- `tools\bench_ollama.py`: Ollama baseline per alias (native API timings; 20,163-token synthetic prompt,
  128 generated tokens; model unloaded first so loads are cold).
- Found why the 9B spilled: Ollama's qwen3.5 tags carry a vision projector layer (9B: 5.63 GB text +
  0.92 GB projector; 4B: 2.65 + 0.68 GB) and load it too. Display holds ~1.0-1.2 GB, so ~6.8 GB is free.
- Pinned serving binaries (`serving\bin.lock`, `tools\fetch-serving-bins.ps1`): llama.cpp v1.0.0 = build
  b12359 (from the v1.0.0 release's nightly-tag.txt; v1.0.0 itself ships no binaries; every numbered
  build is flagged prerelease), CUDA 12.4 x64 build + cudart (driver 591.59 reports CUDA 13.1, so not the
  13.5 build); llama-swap v273. 734.6 MB total, all three sha256 = GitHub's published digests, verified
  before extraction. `serving/bin/` gitignored.
- llama.cpp reads Ollama's GGUF blobs directly (read-only, no second copy of weights).
- `serving\llama-swap.yaml`: aliases coder (9B text), router (4B text), embed (0.6B), all llama-server
  `-ngl 99 -np 1`; chat aliases `-c 65536 -fa on -ctk q8_0 -ctv q8_0 --jinja`; ttl 900 s; 127.0.0.1 only.
  `tools\serve.ps1` starts/stops it on 127.0.0.1:8090 (log `logs\llama-swap.log`).
- `profiles\llamaswap`: base profile with model `coder` at 127.0.0.1:8090 and `context_length: 65536`.
  Gates take a profile now: `gate-smoke.ps1 -Profile`, and `-Model` empty = profile default in both gates.
Numbers (RTX 3070 Laptop 8 GB; prompt 20,163 tokens; 128 generated; n=1 per row):

| Alias | Server | Resident / GPU in use | GPU share | Prompt tok/s | Gen tok/s | Load |
|---|---|---|---|---|---|---|
| coder 9B 64K | Ollama (with projector) | 8.75 GB resident | 64% | 932 | 7.8 | 5.5 s cold |
| coder 9B text 64K q8 KV | llama-server direct | 7.60 GB in use* | 100% | 2,002 | 47.2 | ~6 s to healthy |
| coder 9B text 64K q8 KV | via llama-swap | 7.47 GB in use* | 100% | 2,047 / 2,030 | 50.8 / 50.2 | ~7.3 s cold, ~7.9 s swap back |
| router 4B 64K | Ollama | 5.22 GB resident | 100% | 3,261 | 77.5 | 6.0 s |
| router 4B text 64K q8 KV | via llama-swap | 5.16 GB in use* | 100% | 3,283 | 73.9 | ~5.2 s swap |
| vision qwen2.5vl 7B | Ollama (4K default ctx) | 5.35 GB resident | 100% | 2,275 (2,050-tok prompt) | 67.7 | 8.0 s |
| embed qwen3-embedding 0.6B | Ollama | 1.23 GB | 100% | 53 embeds/s | - | 2.8 s |
| embed qwen3-embedding 0.6B | via llama-swap | 2.65 GB in use* | 100% | 137 embeds/s (256 texts) | - | 3.2 s incl. first call |

*nvidia-smi total including ~1.0-1.2 GB display. Load via llama-swap = wall time minus server prompt and
generation time. Windows "Shared Usage" counter during the 9B run: ~212 MB (no meaningful spill).
qwen3.5 answers were empty in the 128-token benches: the model spends them on reasoning first.

Hermes on the new path (profile llamaswap, alias coder):
- G2 x3: 3/3 pass, 20.5 (cold) / 7.8 / 8.2 s. Same 9B on Ollama: 18-19 s warm. 4B on Ollama: 3/3,
  31.8 / 10.4 / 8.4 s.
- G3: 0 external, 0 guard blocks, task ok, 18.6 s; model traffic only to 127.0.0.1:8090 via the guard.
Gates: G1 pass. G2 pass (base and llamaswap). G3 pass (base and llamaswap). G4 pass. G5 pass (41).
Decisions / surprises:
- 8 GB tier: coder = 9B text on llama.cpp (fits, ~50 tok/s, 6.5x Ollama). The 9B stays main; the 4B
  is the router, not the main model. Quality comparison is still A7's job.
- Base profile stays on Ollama until A5 makes llama-swap primary with Ollama as fallback.
- Vision stays on Ollama: the qwen2.5vl tag is a single combined file; llama.cpp support for it untested.
- No KV-quant change to Ollama: OLLAMA_KV_CACHE_TYPE / flash attention are server-wide and would change
  Atlas's models too. Per-model flags in llama.cpp avoid that.
- Coder + router cannot both stay loaded on 8 GB (7.47 + 5.16 GB); swaps cost ~5-8 s. Embed (2.65 GB
  with display) could co-reside with the router via a llama-swap matrix: later, measured.
- Launcher bug: first serve.ps1 used Start-Process; llama-swap inherited the caller's stdout pipe, so a
  caller piping the script (`| Select-Object -Last 4`) waited forever. Now launched via
  Win32_Process.Create through cmd with a log file; returns in 2 s even when piped.
- Server is stopped at the end of the iteration so the GPU is free for Atlas (ttl would hold the coder
  for 15 min otherwise).
Commit: (see git log, tag a4-done)   Next: A5 LAN provider + fallback.

### 2026-11-17 11:22-11:35 - A5 LAN provider + fallback (part 1: CPU-side; interim checkpoint)
GPU check 11:22: no Atlas batch job, GPU 0%, but Atlas's explorer server (`serve-prod.log`, written 11:22)
is in use and holds qwen3-embedding:0.6b (1.2 GB, ~28 min keep-alive). 2.25 GB in use, so the 6.5 GB coder
would not fit. Not competing with it and not unloading Atlas's model: model runs deferred.
Did:
- Read upstream `user-guide/features/fallback-providers.md`: top-level `fallback_providers` list; custom
  entries take `base_url`; triggers on 429/5xx/401/403/404/invalid responses and (per `hermes fallback list`)
  connection errors; turn-scoped (each new message retries the primary); history kept across the switch.
- `profiles\llamaswap`: `fallback_providers: [custom ariadne-qwen3.5-4b @ http://localhost:11434/v1]`.
  4B not 9B because on Ollama the 9B spills to CPU (7.8 tok/s) while the 4B fits (77.5 tok/s) (A4).
- `hermes fallback list`: chain of 1 entry parsed. `hermes fallback check` (static, no inference): ready.
- `tools\test-failover.ps1`: one Hermes session over three turns (`--resume <session_id>`): turn 1 on
  llama-swap; llama-swap stopped; turn 2 must answer via fallback (evidence: Ollama has the fallback model
  loaded + new agent.log fallback lines); llama-swap restarted; turn 3 must hit llama-swap again (its log
  grows). Mutex-guarded like the gates. Not run yet (GPU).
Gates: not run this part (GPU busy as above; G1 unchanged, no code under test changed upstream).
Next: run gates + failover test when the GPU is free; vision alias; LAN exposure needs the user's decision.

### 2026-11-17 12:18-12:30 - A5 Fallback (part 2) - done
User direction 12:18: cancel schedules, run straight through (PLAN section 4b). Scheduled retry deleted.
GPU 12:19: free (1.7 GB, nothing loaded in Ollama, Atlas idle since 11:42).
Gates: G1 pass; G5 41 passed; G4 pass; G2 base 1/1; G2 llamaswap 1/1 (115.7 s, see below); G3 llamaswap
0 external, 0 blocks (60.3 s, same cause).
Found: **two models on the GPU at once.** G2 base left Ollama's ariadne-qwen3.5-9b loaded (8.7 GB, 5 min
keep-alive); llama-swap then loaded its 9B coder beside it. Windows showed 1.8 GB in shared GPU memory and the
first coder call took 99.8 s (expected ~12 s).
Fix (serving layer, not the tests): `serving\llama_server_exclusive.py`. llama-swap now starts every model
through it: it unloads Ariadne's own Ollama models (`ariadne-*` only, keep_alive=0; never Atlas's), then runs
llama-server inside a Windows job object with KILL_ON_JOB_CLOSE.
Checks (12:24): Ollama 4B loaded -> request coder via llama-swap -> Ollama empty, shared usage 319 MB, coder
45.3 tok/s gen / 1,651 tok/s prompt (wall 23.4 s incl. load); swap to router -> one Ariadne llama-server left;
killing only the venv python launcher -> interpreter and llama-server both exit, VRAM back to 1.3 GB, llama-swap
stays up. (My first attempt at that check matched its own shell by command-line text and killed itself;
redone with an exact process selection.)
Failover (`tools\test-failover.ps1`, one session, 3 turns): PASS. Turn 1 llama-swap 35.8 s; llama-swap
stopped; turn 2 20.7 s on the fallback ("Fallback activated: coder -> ariadne-qwen3.5-4b (custom)" in
agent.log; Ollama had the 4B loaded); llama-swap restarted; turn 3 21.7 s on llama-swap (its log grew; the
launcher unloaded the 4B first).
Not done: vision behind llama-swap (not tried); LAN exposure (user's decision; still loopback only).
Commit: (see git log, tag a5-done)   Next: user redirected 12:30 to architecture first (see next entry).

### 2026-11-17 13:42-14:30 - POC: orchestrator, flows, shared memory, MCP entry points

Architecture approved by the user (13:42), then built as a POC on top of the pinned Hermes, no upstream edits.

- Built: `ariadne\` (orchestrator, flows compiler, shared memory, tasks/memory/git MCP servers, CLI),
  `flows\` (coding, writing, content with one skill each), `plugins\ariadne_phase` (plan phase may only call
  read-only tools; every tool call logged), `profiles\ariadne` (gateway home with the ariadne_tasks MCP server and
  skill), `tools\mcp_call.py` (MCP client standing in for Claude). Hermes `mcp` extra installed (mcp 2.3.0, pinned
  in upstream uv.lock); pytest reinstalled (uv sync had removed it).
- Hermes facts learned: MCP toolsets are `mcp-<server>` (the bare name collides with built-ins such as
  `memory`); MCP tools are `mcp__<server>__<tool>` and may be deferred behind `tool_search`/`tool_call`; worker
  homes need `_config_version: 12`; the venv has ruamel.yaml, not PyYAML.
- Live runs (coder 9B + router 4B on llama-swap, n=1 each, 2026-11-17):
  1. MCP client (stand-in for Claude), coding task "tests fail, fix and commit" in `scratch\poc-calc`:
     routed coding; plan 2 m 33 s, 9 read-only tool calls, 1 write attempt (Hermes built-in memory) blocked by
     the phase plugin; backbrief correct; after approval execute 1 m 55 s (patch, pytest, commit 276560e);
     checks (pytest) passed; status done.
  2. Hermes CLI through the gateway + ariadne-tasks skill, "add subtract() with a test": the chat submitted via
     MCP (first tried bare tool names, then `mcp__ariadne_tasks__submit_task`), showed the backbrief; a resumed
     chat approved it; commit fa6afcf; checks passed; 2 earlier tasks recalled from shared memory.
  3. MCP client, writing task: routed writing; the plan used the terminal, which the writing flow does not have,
     so execute stopped OFF-PLAN -> needs_attention (but the model still wrote a README in the wrong folder);
     revise with feedback -> new backbrief in the right folder -> approved -> done. The note it wrote lists a
     `divide` function that does not exist: small-model accuracy, for A7.
  Fix from run 3: the plan prompt now lists the tools the execute phase will have.
- Tests: G5 60 passed (41 offline_guard + 4 ariadne_phase + 15 orchestrator/flows/memory).

### 2026-11-17 14:23-14:45 - User decisions applied: Chrome, logins, VS Code extension, Pandoc, blocklist

- Decisions (user 14:23, recorded in the Architecture doc): Chrome; real logins by default with a flow.yaml
  switch; VS Code MCP server extension; Pandoc export; SD Turbo images; network open with a per-flow blocklist.
- `flows\mcp_servers.yaml`: `browser` = chrome-devtools-mcp 1.13.0 via npx (`--autoConnect` when the flow uses real
  logins, `--isolated` otherwise; usage statistics, CrUX and update checks off); `vscode` = the extension's
  streamable HTTP endpoint 127.0.0.1:3000/mcp; `export` = `ariadne\export_mcp.py` (Pandoc).
- `flow.yaml` gains `browser.real_logins` and `network.blocklist`; the compiler picks the browser args per flow and
  writes the blocklist into the worker home; `ariadne_phase` blocks any tool call that names a blocked host
  (URL, command or bare domain; subdomains included), in every phase. Coding flow: memory, git, vscode, browser;
  writing and content: memory, browser, export. Read-only browser and editor tools added to the plan allowlists.
- Pandoc 3.14 added to `serving\bin.lock` (GitHub release, sha256 0144b96e...); `fetch-serving-bins.ps1 -Only`
  fetches one entry without re-extracting running binaries. Export smoke test: poc-calc.md -> docx, 11,115 bytes.
- VS Code extension JuehangQin.vscode-mcp-server 0.4.0 installed with `code --install-extension`.
- Not yet run live: the browser server (my smoke test of chrome-devtools-mcp was refused by this session's
  permission check; needs the user to run it or allow it) and the VS Code server (needs VS Code open with the
  server switched on). SD Turbo waits for the user's OK on the download (sd_turbo.safetensors 4.86 GB, or fp16
  parts ~2.4 GB, plus stable-diffusion.cpp CUDA build ~0.9 GB).
- Tests: G5 62 passed (2 new blocklist tests).


### 2026-11-17 14:51-15:10 - Hosting, install, SD Turbo, first delegation (paused at the user's request)

- Hosting: `ariadne\host.py` serves the ariadne-tasks MCP server over streamable HTTP on 127.0.0.1:8791 (`-Lan`:
  all interfaces) behind a bearer token (`.ariadne\token`); verified: /health 200, /mcp without token 401, with
  token list_tools + list_tasks OK. `tools\host.ps1` starts models + endpoint, `-Install` adds a logon task.
  Port 8765 was taken by another local app, hence 8791.
- Install: `tools\install.ps1 -Check` reports every dependency; on this machine all present (SD Turbo then
  missing, now fetched). Native, not containerised (GPU + desktop browser/editor tools).
- SD Turbo: stable-diffusion.cpp master-1106-532d2c1 (CUDA 12) and sd_turbo.safetensors (5.21 GB, sha256 verified,
  HF commit b261bac6) installed.
- Entry points narrowed by the user: Slack, terminal, MCP.
- First delegation to Ariadne: task t1117-145455-0d79 (coding flow) writes `ariadne\image_mcp.py` + tests from a
  brief in `scratch\briefs\image_mcp.md`. Plan took ~8 min (first model call ~4 min: the browser MCP adds ~30 tool
  schemas to the prompt); backbrief approved 15:03; executing when paused. Its output is NOT committed: review first.
- Known issue: the vscode MCP server fails to connect (VS Code not serving) and Hermes retries every ~70 s.

### 2026-11-17 15:15-15:35 - Cross-platform CLI, dependency gate, coding flow beta, README

- `python -m ariadne` (stdlib-only bootstrap): doctor, install [--system], up/down, serve, connect, token, task, chat,
  profile, flows. Every command except doctor/install runs the dependency check first and stops with the fix.
- PowerShell tooling removed (old gate/egress scripts kept in tools/legacy/). bin.lock now has windows-x64,
  linux-x64 (CUDA 12.8) and darwin-arm64 (Metal) entries; llama-swap.yaml is a template rendered per machine.
- Shipped scope: coding flow (beta) with memory + git servers; writing/content moved to flows/_experimental/; Slack TODO.
- Delegation result: the image MCP task produced unusable code (wrong MCP API, ignored the brief); cancelled and
  rewritten by hand (ariadne/image_mcp.py). Live: SD Turbo 512x512 -> 593,651-byte PNG.
- Live on the new CLI: `serve` start/stop, `up` (/health ok), coding task "add divide()" plan -> approve -> done in
  ~2 min, commit e435d8f, 5 tests pass. Unit tests 68 passed. Linux/macOS paths not yet run on real machines.
- README rewritten: branding (Ariadne in Naxos, De Morgan 1877, public domain), architecture and lifecycle PNGs
  (docs/diagrams/*.mmd rendered via mermaid.ink), install/run/connect only.
