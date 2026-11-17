# Ariadne execution plan

Written 2026-11-16 so that any model (or person) can continue without the earlier conversation.
Read this file, then `WORKLOG.md` (status + iteration log).
End goal: a local-only agent harness built ON Hermes Agent (not a rewrite of it), that keeps taking upstream
Hermes improvements with little effort. Ariadne = a pinned upstream Hermes + Ariadne plugins, profiles,
skills and packaging.

---

## 1. Hard rules

1. **Local only.** Nothing Ariadne does at runtime may call a host outside the machine or the LAN. No GitHub,
   no cloud model providers, no OpenRouter. Never create remote repos or push anywhere.
2. **Touch only `C:\repos\ariadne`.** Every other folder under `C:\repos` is the user's own project:
   read-only. In particular never write to `C:\repos\atlas`.
3. **Never edit `upstream\` by hand.** It is a pristine Hermes checkout at the commit in `hermes.lock`.
   A change Hermes cannot take through a plugin, hook, config or MCP server goes in `patches\` as a numbered
   patch applied by `tools\apply-patches.ps1`, with a note in WORKLOG saying why no extension point worked.
   Prefer, in order: config > MCP server > skill > plugin/hook > patch.
4. **Isolated Hermes home.** Always run Hermes with `HERMES_HOME=C:\repos\ariadne\.hermes-home`. Never read
   or write `%USERPROFILE%\.hermes`.
5. **Commits.** Local git only, in `C:\repos\ariadne`, under the user's own git identity (already configured).
   No AI co-author lines, no attribution trailers. One commit per finished iteration.
6. **Measure before you claim.** Every number goes in `WORKLOG.md` with n, method, model, date.
   Never tune a test until it passes. Never copy a number from memory; re-read the log.
7. **One issue per iteration.** After each iteration: run the gates, update `WORKLOG.md`, commit, send the
   user a summary of at most 15 lines, then schedule a 30-minute pause before the next one.
8. **Ask the user first** before: deleting anything you did not create, downloading a model or package
   bigger than 2 GB, anything that leaves the machine beyond fetching pinned packages/models, a job longer
   than 2 hours, or changing the order of this plan.
9. **One GPU job at a time.** Atlas shares this GPU. Before any GPU-heavy run, check `nvidia-smi`; if
   another job is using it, wait or ask.

## 2. Environment and layout

| Thing | Value |
|---|---|
| Machine | Windows 11, Ryzen 7 5800H, 32 GB RAM, RTX 3070 Laptop 8 GB, 127 GB free on C: (2026-11-16) |
| Python | Ariadne venv `.venv` on uv-managed Python 3.14.8 in `.tools\python` (upstream lock resolves only for 3.14); deps via `uv sync --project upstream --frozen --no-dev` with `UV_PROJECT_ENVIRONMENT=.venv`; uv 0.13.1 |
| Models (Ollama, `localhost:11434`) | qwen3.5:9b (6.6 GB), qwen3.5:4b (3.3 GB), qwen2.5:7b, qwen2.5vl:7b, qwen3-embedding:0.6b, nomic-embed-text |
| Hermes | `upstream\` at the commit in `hermes.lock` (MIT, Nous Research) |
| Hermes home | `C:\repos\ariadne\.hermes-home` (gitignored) |
| Local Ollama as provider | `provider: custom`, `base_url: http://localhost:11434/v1` (from upstream docs `guides/local-ollama-setup.md`) |

Hermes refuses models served with under 64,000 tokens of context, so local models run as Ariadne Ollama tags with num_ctx 65536 (`serving\ollama\*.Modelfile`). 8 GB VRAM is the real limit: 27B-class models do not fit on the GPU. Starting set: `coder`/main =
qwen3.5:9b, `router`/auxiliary = qwen3.5:4b, `vision` = qwen2.5vl:7b, `embed` = qwen3-embedding:0.6b.
Bigger models (e.g. a 35B-A3B MoE with experts on CPU) are an experiment in A4, not an assumption.

```
ariadne\
  PLAN.md  WORKLOG.md  README.md  hermes.lock  .gitignore
  upstream\        pristine Hermes clone (own .git, gitignored by the Ariadne repo)
  plugins\         Ariadne Hermes plugins (graph memory, context engine, offline guard, ...)
  profiles\        one config per workflow: coding, designing, writing, investigating
  skills\          Ariadne skill tap
  patches\         numbered patches to upstream, only when unavoidable
  serving\         llama-swap / gateway configs for LAN model serving
  packaging\       offline bundle, model manifest, SBOM
  tools\           scripts: gates, apply-patches, bump-upstream, egress check
  evals\           Ariadne task suites and results
```

**Upgrade flow (the point of this layout):** `tools\bump-upstream.ps1 <commit>` fetches upstream, checks out
the commit, re-applies `patches\`, runs all gates, and only then rewrites `hermes.lock`. A failing gate means
fix the plugin (or drop a patch that upstream made unnecessary), never edit upstream.

## 3. Regression gates (run at the start of every session and after any change)

| Gate | Check | Pass if |
|---|---|---|
| G1 upstream intact | `git -C upstream rev-parse HEAD` and `git -C upstream status --short` | HEAD = `hermes.lock`; only files touched by `patches\` differ |
| G2 smoke | Hermes, isolated home, local model, one prompt that needs one tool call | answers, tool call succeeds, exit 0 |
| G3 egress | outbound connections during G2 | only loopback / LAN addresses |
| G4 plugins | `hermes plugins doctor` on each Ariadne plugin | all pass |
| G5 unit tests | `pytest` over `plugins\` and `tools\` | all pass |

Gates G2-G5 come online as the iterations that create them finish; WORKLOG lists which are live.
If a live gate fails: stop, find the change, fix or revert, re-run. Do not continue on red.

## 4. Iterations, in order

Each has: goal, steps, pass line, and what to do if blocked. Each ends with a checkpoint (section 5).

### A0. Scaffold - done 2026-11-16
Hermes clone moved to `upstream\`, Ariadne repo created around it, PLAN/WORKLOG/README/hermes.lock written,
first checkpoint committed.

### A1. Baseline: stock Hermes on local Ollama, isolated home - done 2026-11-16
- Create `.venv` in `C:\repos\ariadne` with uv; install `upstream` editable into it (no global installs).
- `HERMES_HOME=C:\repos\ariadne\.hermes-home`; config: `provider: custom`, base_url Ollama, model qwen3.5:9b.
- Run a one-shot prompt that needs a file-read tool call. Write `tools\gate-smoke.ps1` (G2).
- **Pass:** G2 green 3 runs out of 3. Record time to first token and total time.
- **Blocked:** if Windows install fails, try WSL2 only after asking.

### A2. Egress audit - done 2026-11-16
- Run G2 while logging every TCP connection the Hermes process tree opens (`Get-NetTCPConnection` polling
  by PID, plus a dead `HTTPS_PROXY` run to surface hidden calls). Grep startup paths for update checks,
  telemetry, model discovery, remote config.
- Write `tools\gate-egress.ps1` (G3) and a table in WORKLOG: host, which code, needed?, how to turn off.
- **Pass:** a list of every outbound host with its source; G3 written (may be red until A3).

### A3. Offline guard (first Ariadne plugin) - done 2026-11-17
- A2 found config alone closes all observed egress (switches in `profiles\base`). A3 adds defense in depth: a `plugins\offline_guard` plugin (hooks / tool filter) that
  blocks non-local hosts and logs attempts. Patch only if neither works.
- **Pass:** G3 green; G4 + G5 live for this plugin.

### A4. Model serving on this machine
- llama-swap (pinned, checksum-verified) in `serving\` with aliases `coder`, `router`, `vision`, `embed` over
  llama.cpp or Ollama. Measure: swap time per model, tokens/s, VRAM. Try one MoE with CPU-offloaded experts.
- **Pass:** all four aliases answer through one URL; numbers recorded; a recommendation for the 8 GB tier.

### A5. LAN provider + fallback
- Point Hermes at the serving gateway by alias; local Ollama as `fallback_chain`. Kill the gateway mid-session.
- **Pass:** session continues on fallback; switch logged.

### A6. Upgrade drill (proves the strategy early)
- Write `tools\bump-upstream.ps1`. Bump `upstream` to the newest upstream commit, run all gates.
- **Pass:** bump + gates in under 15 minutes with zero manual edits; time recorded.

### A7. Tool-call reliability on small models
- Fixed suite of 30 tool-using tasks in `evals\`. Compare plain vs grammar/JSON-constrained tool calls.
- **Pass:** success rate per model and mode with n and intervals; pick defaults.

### A8. Workflow profiles - coding first
- `profiles\coding` with Serena + Git MCP servers (pinned), coding skills. Then designing, writing, investigating.
- **Pass:** one real coding task end to end offline on one of the user's repos (read-only copy in scratch).

### A9. Graph memory (memory-provider plugin)
- `plugins\graph_memory`: SQLite + local embeddings; nodes link back to raw log spans.
- **Pass:** a fact written in session 1 is retrieved with its source in session 2; G5 tests.

### A10. Context engine (compressor -> graph)
- `plugins\context_engine` using the `router` model to write structured graph updates instead of summaries.
- **Pass:** tokens re-read after a model switch drop vs stock compression, with task success not worse.

### A11. Per-step routing
- Check whether a pre-LLM hook can change the model per call; else delegation provider; else a patch.
- **Pass:** routing decision logged per step; no regression on A7 suite.

### A12. Offline bundle
- Vendored wheels, model manifest with sha256, SBOM, one installer; install on a machine with no network.
- Ship a local models.dev snapshot (A3: refresh is pointed at a dead loopback port today).
- `ariadne` launcher: sets HERMES_HOME and ARIADNE_GUARD_ALL_PROCS=1; decide dead HTTPS_PROXY with NO_PROXY
  from the guard allow-list; offer (ask first) an OS outbound firewall rule for the venv and its children.
- **Pass:** fresh install passes G1-G5 offline.

## 5. Checkpoints and progress records

Every iteration (and every meaningful stopping point inside a long one) ends with a checkpoint:

1. Run the live gates; paste results into the WORKLOG entry.
2. Append a WORKLOG entry using the template below. Update the Status table at the top of WORKLOG.
3. Commit in `C:\repos\ariadne`: `git add -A; git commit -m "A<n>: <what changed>"` - user's identity,
   no trailers. Tag finished iterations: `git tag a<n>-done`.
4. Send the user at most 15 lines: what changed, numbers, gate state, next iteration.
5. Schedule a 30-minute pause, then continue with the next iteration.

To roll back to a checkpoint: `git checkout a<n>-done` (or `git reset --hard <commit>` after asking).

**WORKLOG entry template**
```
### <date time> - A<n> <title>
Goal:
Did:
Numbers: (metric, value, n, method, model)
Gates: G1 _ G2 _ G3 _ G4 _ G5 _
Decisions / surprises:
Commit: <hash>   Next:
```

## 6. Prompt to resume in a new session

"Continue Ariadne. Read C:\repos\ariadne\PLAN.md, then WORKLOG.md. Run the live gates, then do the next
unfinished iteration, one issue at a time, with a checkpoint and a 30-minute pause after each."
