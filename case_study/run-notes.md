# Validation notes (raw, for the case study)

Machine: RTX 3070 Laptop 8 GB, 32 GB RAM, Windows. llama.cpp b12359, llama-swap v273, Hermes pinned 458a0046ad.

## Run 1 - coding flow, todo app (sandbox/todo)

- 17:08 first attempt t1117-170813-2133 failed at plan: Hermes refuses `--continue NAME --create-if-missing` with
  -m/-t/--max-turns/-s ("creation overrides are unsupported on resume"). Fix e8f3753: start a segment's Hermes
  session with full args, record the printed session_id, resume by id without overrides.
- Worker process was still the old code; restarted it, requeued (lesson: worker should restart when code changes).
- 17:13 t1117-171246-b7bd planning on qwen3.8-27b (17.7 GB, mostly CPU): 14 min to backbrief (17:13:18 -> 17:27:30).
- Backbrief quality: good. 5 steps, per-step models (27B for code, 9B for tests, Gemma 26B-A4B MoE for README),
  checks include id-stability smoke test, risk about Windows subprocess cwd noted. Did not prefer MoE for code.
- KV: plan parked only 561 tokens -> Hermes title generation (aux call on the main model) ran after the run and
  replaced the slot. Fix 9934b35: title_generation.model_upgrade_enabled false.
- 17:33 approved; 17:33:48 woke 561 tokens from the plan cache in 0.8 s.

## Desktop

- First build failed: npm_config_* inherited from an npx parent broke pnpm's preinstall check. Fix f73bec9.
- Second build OK: upstream/apps/desktop/release/win-unpacked/Hermes.exe (build-only, not launched yet).

## 18:05 check

- Plan checkpoint: 17:33:48 -> 17:44:50 (11 min). It had to prefill ~13.6K tokens (cache held only 561 because of
  the title bug) and write a 4.5K-char handoff at ~2 tok/s. Parked 13,596 tokens as checkpoint in 1.8 s.
- Steps 1-2 on qwen3.8-27b since 17:44:50; at 18:06 still no files written. Measured decode: 2.17 tok/s
  (slot API through llama-swap /upstream/<model>/slots - this also confirms the KV park/wake path works).
- A qwen3.5-9b load happened between two 27B loads (unknown requester - to investigate; costs two swaps).
- Takeaway so far: the dense 27B at ~2 tok/s (thinking on) makes a small app take hours on 8 GB. MoE (3B active)
  should be ~10x faster here; consider default MoE for execution, 27B for planning only, and reasoning off/low
  for execute steps.

## 18:16 decision (Adnan approved)

- 27B plans only; steps that name no model run on qwen3.6-35b-a3b (MoE); Hermes --reasoning low for execute.
  Commit 6aebd6b. Downloading qwen3.6-35b-a3b (22.4 GB).
- Run 2 (t1117-171246-b7bd) cancelled after 32 min of steps 1-2 with no file written yet.
- Run 3 t1117-181646-9cd0 (session todo-run3) queued behind the design task t1117-173412-6482.

## 18:38 check

- The mid-run qwen3.5-9b loads were my own --resume probes at 17:10-17:11 (agent.log), not Ariadne. No bug.
- Hermes agent.log has per-call metrics: in/out tokens, latency, prompt-cache hits (e.g. cache=4008/4033 99%).
  Use these for the case study.
- Design run t1117-173412-6482 (gemma-4-26b-a4b MoE): plan 18:17:11 -> 18:27:59 (11 min). KV park reported
  "0 tokens in 326 s" - odd (the save itself, or a reload behind it); investigate.
- Design backbrief: structurally right (5 steps, check/render/embed, all sections listed in CHECKS, risks on
  sequence-diagram syntax and 2M-doc scale), thin on design content - the design itself happens in step 2.
  Approved at 18:39 with 1=gemma-4-26b-a4b (planner put a mkdir on qwen3.5-9b: a model swap for nothing).
- Todo run 3 planning on 27B since 18:28.
- qwen3.6-35b-a3b download 20.8/20.8 GiB, verifying.

## 19:05

- Todo run 3 plan TIMED OUT (run_budget 900 s) on the 27B: 18:28 -> 18:52; KV save then took 411 s (llama-server
  kept generating after Hermes was killed; save waited for the slot). Plan budget raised to 2700 s (fa094b0).
  KV file for 15.9K tokens of the 27B: 1.7 GB.
- Design run (gemma-4-26b-a4b, ~6 tok/s decode vs 2.2 for the 27B): plan checkpoint took 2 min (vs 11 on 27B).
  Execution wrote DESIGN.md (4.6 KB) + 3 diagrams (mmd/svg/png) via the diagram MCP server - render path works.
- DESIGN.md is a real design but thin (~60-65%): all sections present; gaps - keyword index never fed in the
  diagram, permission filter `doc_id IN allowed list` does not scale to 2M docs (needs ACL principals per chunk +
  group expansion), no concrete stack choice (FAISS/Chroma/Qdrant "or"), embeddings not tied to the catalog
  (qwen3-embedding), scale/numbers missing, only one of three diagrams linked as PNG.
  -> iterate: second task in session rag-case-study with this feedback, and feedback_task for skill learning.
- New feature (Adnan 19:01): learned skills per flow from feedback (fa094b0).

## 19:25

- Design run 1 done 19:05 (exec 18:55 -> 19:05, 10 min on gemma). KV: woke 22,587 tokens in 4.6 s; parked in 6.8 s.
- Final checkpoint failed: Hermes also rejects --run-budget on --resume (fixed 5213dad).
- New (Adnan 19:17/19:18): check gates required before any task starts (awaiting_gates asks for them); QA =
  flow checks + command gates + reviewer-judged review gates; execute->QA loop up to 10 rounds, stops early when two
  rounds in a row fail as many gates (4871d1b). Feedback is processed before new tasks (ce169cb).
- Feedback sent on design run 1 -> design-lessons skill (learn job queued).
- Design iteration 2 t1117-192137-38af (7 gates) planning; todo run 4 t1117-192142-6cb9 (5 gates) queued.
- Waste spotted: iteration 2's plan woke the segment's execute-phase cache (22.6K tokens, 16 s) although it starts
  a new Hermes session (plan/gemma != execute/gemma) - the prefix does not match. Key KV by segment+phase signature.

## 19:32

- Design iteration 2 backbrief (19:21 -> 19:25, 4 min on gemma with a warm cache): maps all 7 gates to steps.
  Flaw: step 2 "internal reasoning, no tools" on qwen3.6 then step 4 writes on gemma - across a model boundary the
  content would be lost (separate sessions, summary only). Approved with all=gemma-4-26b-a4b; sent the lesson as
  feedback; planner prompt now says steps hand over through files (8752ecd, applies after worker restart).
- Todo run 4 planning on the 27B since 19:25.

## 21:02

- Todo run 4 plan: 19:25 -> 20:00 (35 min on the 27B, 17.7K tokens). Excellent plan (smoke test existing code,
  tmp_path tests, .gitignore for a clean tree, G3 sequence as a test). Approved with all steps on qwen3.6.
- Design iteration 2 execute timed out at 30 min (20:02 -> 20:36): DESIGN.md rewritten (11 KB, 20:14), new
  datamodel.mmd, but diagrams not re-rendered. Task marked failed -> fixed: a timed-out run now goes to the gates
  and the loop continues (91ef57f); design execute budget 60 min. Iteration 3 t1117-210011-ba07 queued.
- design-lessons SKILL.md created 20:43 from the feedback (component choice, ACL principals per chunk, sizing,
  diagram completeness, link all outputs) - good, specific. Loaded via -s in later design runs (seen in cmd line).
- Lesson: llama-swap -watch-config reload (I re-rendered the config at 20:52) restarted gemma mid-request and broke
  a running learn job. Config must only change between tasks.
- RAM: 0.5 GB available of 31.9, 47.5 GB committed, llama-server 14 GB. Shared GPU memory = same RAM.
  gpu.shared_gb=6 (1c7d552) takes effect on the next model load: measure qwen3.6 tok/s.
- Worker handover at 20:36 worked; worker now self-restarts on code change (b2f9d42).
- Queue: learn job -> todo exec -> design iteration 3 -> RAG build plan.

## 21:15 resource profiles

- Adnan: profiles max / shared / light (5053455). Set to max: --fit-target -14653 --prio 2 -lm mmap+mlock.
- 21:14 with max on the 27B (todo plan checkpoint): GPU 100%, 7.5 GB VRAM, shared GPU memory 12.2 GB in use
  (was 0.2 GB), RAM available 0.4 GB. tok/s still to measure (was in prompt processing).
- Found: a killed/timed-out Hermes client leaves its request running in the per-home Hermes gateway; it later
  reloaded gemma over the 27B mid-task. Fix 57d5259: stop the home's gateway on timeout; gateway stop needs --yes.
- Killed a learn run stuck since the 20:52 config reload; it reported "no update" and the queue moved on.

## 21:33 max profile measured

- qwen3.8-27b with max (14.6 GB into shared GPU memory, mlock): 0.35 tok/s decode, GPU 100%, 219 pages/s,
  RAM available 3.2 GB. VRAM-only + CPU (17:xx): 2.17 tok/s. Shared GPU memory makes the dense 27B ~6x slower:
  every token streams the shared part over PCIe.
- Todo plan checkpoint has run 25+ min (21:06 ->) because of it.
- Shared skills now in the repo (aa8aeb5, 2115ea1, 6f0549c).

## 22:10 todo run 4 executing on qwen3.6

- 21:39 execute on qwen3.6 (MoE) after the 27B checkpoint was stopped; by 21:53 tests written; commit 8480a7e
  "Add stdlib todo app with JSON storage and tests" in sandbox/todo.
- QA: review gates 4/4 passed (reviewer run), but the command gate `python -m pytest -q` failed: the harness runs
  gates in the system shell, where `python` is C:\Python313 without pytest (the agent ran its tests elsewhere).
  Iterating (attempt 3). Design question: checks and the agent's terminal must share one environment - per-
  workspace venv later; for now the agent can install pytest where the gate runs.
- KV: woke 20,568 tokens in 1.8 s for the QA checkpoint.
- Planner/default swapped to qwen3.6-35b-a3b (84b3650) per Adnan.

## 2026-11-18 02:16 check-in
- Design iter 3 (t1117-210011-ba07, all=gemma): attempt 2 used its 60-min budget, QA 5/7 (G2 ACL-per-chunk wording failed); attempt 3 also hit the budget at 02:13, QA running. ~1 h per attempt on gemma under CPU contention (desktop build ran 22:45-23:00).
- RAG build (t1117-202509-ce9e) approved all=qwen3.6-35b-a3b, queued behind the design task.
- qwen3.6-35b-a3b decode ~18 tok/s (4659 out / 259 s).
- Sign-off lessons folded into skills/coding/planning-lessons (ca84e0d): one model per codebase, evidence after the run, stay in the brief.
- Desktop: chat waited 99 s behind a gemma generation (one slot). Built deliberate park/resume + status plugin (9b22245).

## 2026-11-18 03:05 check-in
- Design iter 3: attempt 3 QA 6/7 (G2 ACL fixed); only G7 left (datamodel.png/svg not rendered). Attempt 4 running since 02:21.
- My read of DESIGN.md: a real design now (ACL principals on every chunk + query-time filter, Qdrant hybrid, marker, reranker, 2M-doc sizing, eval, V1 scope) ~75%. Defects the gates missed: the file holds two designs (new one appended over the old: Overview/Requirements/Diagrams twice, 306 lines); architecture/query PNGs are from 19:01, older than their .mmd edits (02:29); generator says Llama-3-8B, not a model in our catalog; RAM estimate light (20M x 1024-d fp32 vectors ~80 GB before HNSW).
- Lesson for review gates: check the document has each section once, and rendered images are newer than their sources.

## 2026-11-18 03:55 check-in
- Attempt 4: no file changed in an hour. Root causes found in the design home's agent.log:
  1. Hermes write_file refused 21 times: 'Refusing to overwrite DESIGN.md: last read with offset/limit pagination'. Gemma never read it whole or used patch; earlier it appended instead -> the duplicated design.
  2. render_diagram was called with relative paths ('diagrams/x.png'); the MCP server resolved them against its own cwd -> renders landed in C:\Users\alama\diagrams (outside the workspace; left for the user to delete). Workspace PNGs stayed stale, so G7 kept failing.
- Fixes: diagram/image/export MCP tools now refuse relative paths with a clear message (db0890e); design-lessons skill: read whole or patch, absolute tool paths, check renders/duplicate sections before finishing (7880295).
- Attempt 5 (started 03:35) still runs on the old server code; expect a no-progress stop, then a short follow-up iteration.

## 2026-11-18 05:16 check-in
- Design iter 3 t1117-210011-ba07: stopped after attempt 5 (no progress 2 rounds): 6/7, only G7 (datamodel render) failing. DESIGN.md duplication fixed in attempt 5 (177 lines). Old-MCP-code renders went to C:\Users\alama\diagrams.
- RAG build t1117-202509-ce9e started execute 04:45 on qwen3.6-35b-a3b (new worker code: park, absolute-path MCP tools).
- Follow-up design finishing pass t1118-051537-e531 queued behind it (brief sandbox/briefs/rag-design-4.md): renders with absolute paths, catalog models, RAM math; 2 command gates + 3 review gates.

## 2026-11-18 06:05 check-in
- RAG build attempt 1 (04:45-05:25): Hermes hit its 40-turn limit (max_iterations_reached) -> exit 1 -> worker marked the task failed instead of checking gates. Code so far: rag/ (acl, chunker, embedder, eval, generator, index, retrieval, CLI), tests/, eval/golden.yaml, acl.yaml; no commits; a debug_bm25.py left in the root. Last thing it found: BM25 gives negative IDF on a one-document corpus and search_bm25 filtered > 0.
- Also: Hermes' terminal blocks python -c one-liners in -Q mode ('script execution via -e/-c flag').
- Fixes: turn-limit end now goes to the gates like a timeout; coding execute turns 40 -> 80 (e90ce8f); planning-lessons: no one-liners, scratch scripts out of the tree, turn budget.
- Re-queued the RAG build (same plan/models). Approved the design finishing pass t1118-051537-e531 with all=gemma-4-26b-a4b (planner wanted 3 models incl. an 18.8 GB gemma-4-31b download); it runs first.

## 2026-11-18 06:55 check-in
- Design finishing pass attempt 1: renders now land in the workspace (absolute paths). DESIGN.md (197 lines, 06:53) names qwen3.6-35b-a3b + embed, RAM math 20M x 1024 x 4 B x 1.3 = 106.5 GB (correct). My read: ~85%.
- But the PNGs were rendered at 06:17, before the 06:53 edit: architecture.png still shows 'Generator: Llama-3' while DESIGN.md's embedded Mermaid says qwen3.6. Source of truth split between diagrams/*.mmd and the Mermaid blocks in DESIGN.md.
- My gate bug: render_diagram rewrote the .mmd on the SVG call, so every PNG looked older than its .mmd -> command gate G1 could never pass. Fixed (a882878): unchanged .mmd is left alone. Next attempt re-renders and should pass.
- Lesson for design-lessons: one source per diagram (diagrams/*.mmd); DESIGN.md embeds it, render after the last edit.

## 2026-11-18 07:42 check-in
- Design finishing pass attempt 1: review gates 3/3; only the render-freshness command gate failed (my tool bug, fixed a882878). Attempt 2 (from 07:19) fixed architecture.mmd (Generator: qwen3.6-35b-a3b, Embedder: embed) and re-rendered all diagrams at 07:35; both command gates pass when I run them. architecture.png checked visually: matches DESIGN.md.
- Verdict: the design meets the 80% bar (~85%): decided components, ACL principals per chunk with query-time filter, sizing with checkable math, eval plan, V1 scope, four rendered diagrams that match the text. Open: disk estimate (150 GB) is asserted, not derived.
- RAG build queued next.

## 2026-11-18 08:30 check-in
- Design finishing pass t1118-051537-e531: DONE 08:27 (attempt 2; review 3/3, both command gates pass). Design iteration total: v1 thin (~60%), iter 2 timeout, iter 3 6/7 then stall (write_file refusal, relative render paths), finishing pass done -> ~85%.
- Report wording bug: 'checks: none defined' when only task command gates exist; fixed.
- RAG build t1117-202509-ce9e re-run started 08:27 on qwen3.6 (80 turns).

## 2026-11-18 09:20 check-in
- RAG build re-run (08:27-09:14, 43/80 turns, clean stop): fixed the BM25 bug (negative IDF on tiny corpora; own SQLite connection in _rebuild_bm25), 24/24 tests pass (I re-ran: 24 passed), committed 9c25af7, clean tree, debug_bm25.py gone.
- But it declared Done after that fix: steps 6-9 (corpus checkout, golden set, README with real transcripts, real ingest/ask/eval) not done; corpus/ empty, no README. The resumed run narrowed to the last open item instead of the remaining plan. QA should fail G2-G5 and iterate with the failing list.
- Possible harness improvement: on a re-run, tell the executor which plan steps have no evidence yet (not only failing gates).

## 2026-11-18 10:05 check-in
- RAG build QA after re-run: 2/6 review gates (pytest passed); 4 failing (README with ingest counts, ask transcript, eval >= 0.7, ...). KV woke 38K tokens in 2.2 s for the QA checkpoint. Iteration 2 started 09:42; corpus now checked out (227 files), README not yet written.
