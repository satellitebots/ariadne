# TODO

Parked ideas and open work. The current state is in [wiki/Status-and-Roadmap.md](wiki/Status-and-Roadmap.md), and
the reasoning behind the fixed rules is in [wiki/Decisions.md](wiki/Decisions.md).

## Now

- [ ] **Stocks case study.** An independent Python package that pulls Yahoo Finance data and computes analytics,
      built end to end through Ariadne on jobs and the coding standards. Analytics only, not financial advice.
      Write-up in `case_study/`, code exported with `ariadne casestudy export`.
- [ ] **Calibrate the skills from that run:** `jobs`, `coding-standards`, `web-and-browser`, `planning-lessons`.
- [ ] **Finish RAG build v1** on the jobs runner. It needs the ingest, ask, eval and README, then a clean tree. See
      [the RAG case study](case_study/RAG_case_study.md#where-it-stands).
- [ ] First real run of debug-mode logins (`need_login` → sign in → resume).

## Parked ideas

### Ways in
- [ ] **Chat hijack as the main flow.** You just chat; Ariadne picks up the work from the chat session and runs the
      drill in the background, instead of you submitting tasks explicitly.
- [ ] Slack channel.
- [ ] Bind the MCP endpoint and desktop to the LAN (`up --lan`), behind the token. This needs a firewall decision
      first.

### Machines and scale
- [ ] **Load-balance across the two home servers.** One has 64 GB RAM and no GPU, for CPU inference of MoE models
      out of RAM.
- [ ] Measure CPU-only throughput on that server before routing work to it (tokens/s per model, by active
      parameters).
- [ ] Run jobs on another machine while the GPU box keeps the model.

### Quality
- [ ] **Compression telemetry as a health check.** Track the reduction and seconds per pass (median 22% and 85 s
      today), and decide the threshold for "good compression".
- [ ] **Instruction decay** over long sessions: measure whether skills and rules are still followed late in a
      segment; re-inject them at checkpoints if not.
- [ ] Default code-quality gates added by the flow (ruff, mypy, pytest, bandit as jobs), not just suggested by the
      skill.
- [ ] One Python environment per workspace, shared by the worker's terminal, jobs and gate commands.
- [ ] Restart the worker automatically when Ariadne's own code changes (it ran stale code once).

### Flows and app
- [ ] Validate the design, writing and content flows end to end.
- [ ] Desktop: run and validate it (last). Show `need_login` and jobs in the status chip.
- [ ] Watch window: show running jobs and their progress lines.
