"""A mock backend for the UI: the real verbs, store, engine and machine broker, with a scripted worker, a scripted
orchestrator and a fake model server. No GPU, no model, no daemon.

    python -m ariadne ui --mock [--port 8918]

State lives in a throwaway folder (ARIADNE_STATE, a temp dir unless set). It is seeded with tasks and drafts in
every state, and runs keep flowing: a run steps through its work, pushing tool calls, model calls and job output as
it goes, so park, steer, resume, cancel, approve and reject all behave as they do for real. One task asks
permission midway; one loops for a while; one fails its final review. When nothing is queued for a little while, a
demo task runs again, so there is always something live.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

if __name__ == "__main__" or os.environ.get("ARIADNE_MOCK") == "1":
    os.environ.setdefault("ARIADNE_STATE", tempfile.mkdtemp(prefix="ariadne-mock-"))

from . import durable, engine as enginemod, flows as flowlib, jobs, park, paths, permissions, spec as speclib, verbs  # noqa: E402
from .broker import Broker  # noqa: E402

PACE = float(os.environ.get("ARIADNE_MOCK_PACE", "1.6"))    # seconds between a mock worker's actions


class FakeServer:
    """llama-swap as far as the broker can tell: loads what it is asked for, instantly."""
    def __init__(self):
        self.loaded = []

    def up(self):
        return True

    def start(self):
        pass

    def running(self):
        return list(self.loaded)

    def unload(self):
        self.loaded = []
        return True


# ---------- scripted work ----------

def _work(title, outputs):
    """What a mock worker does in a step, as (kind, detail) actions, chosen by the step's title."""
    t = title.lower()
    if "bound" in t or "plan" in t:
        acts = [("tool", "read NOTES.md"), ("model", "model call 1: 10,316 tokens in, 921 out, 41 s"),
                ("tool", "wrote NOTES.md"), ("model", "model call 2: 11,337 tokens in, 58 out, 7 s")]
    elif "source" in t or "gather" in t or "research" in t:
        acts = [("tool", "searched the web: Alphabet Q3 2026 results"), ("tool", "fetched https://abc.xyz/investor/"),
                ("model", "model call 3: 14,902 tokens in, 311 out, 12 s"),
                ("tool", "searched the web: Reuters Alphabet capex November 2026"),
                ("tool", "fetched https://www.reuters.com/technology/alphabet-capex-2026-11-20/"),
                ("tool", "wrote SOURCES.md"), ("model", "model call 4: 17,880 tokens in, 402 out, 15 s")]
    elif "fact" in t or "data" in t or "pull" in t or "compute" in t:
        acts = [("tool", "wrote scripts/facts.py"), ("job", "submit"),
                ("model", "model call 5: 12,883 tokens in, 65 out, 9 s"), ("tool", "read data/facts.json")]
    elif "verify" in t or "check" in t or "review" in t:
        acts = [("tool", "read REPORT.md"), ("tool", "read data/facts.json"),
                ("tool", "ran: python checks/facts_in_report.py REPORT.md data/facts.json"),
                ("model", "model call 7: 21,440 tokens in, 512 out, 19 s"), ("tool", "edited REPORT.md")]
    elif "loop" in t:
        acts = [("tool", "ran: ls scripts/build.py")] * 6 + [("tool", "wrote scripts/build.py")]
    else:
        acts = [("tool", "read NOTES.md"), ("model", "model call 6: 18,220 tokens in, 1,804 out, 64 s")]
        acts += [("tool", f"wrote {o}") for o in outputs] + [("model", "model call 7: 20,101 tokens in, 120 out, 9 s")]
    return acts


MOCK_PLAN = ["Exam format: weights and what the final covers", "Dynamic programming: LIS, LCS, knapsack",
             "Divide and conquer: master theorem, FFT, median of medians", "Graphs: SCC, 2-SAT, MST",
             "Max flow: Ford-Fulkerson, Edmonds-Karp, min cut", "Linear programming: duality, simplex",
             "NP-completeness: reductions, halting problem"]


class MockWorker:
    """Stands in for engine.hermes_step: walks a step's scripted actions, pushes them as progress, honours park,
    ask and cancel between actions, writes the step's outputs, submits a job where the step has one, and answers
    review checks. A resumed session continues where it stopped."""
    def __init__(self, pace=PACE):
        self.pace, self.pos, self.step_of = pace, {}, {}       # session -> next action index, step number

    def __call__(self, flow, kind, prompt, ws, ref, model, tools, session=None, stop=lambda: False,
                 on_progress=None, **_):
        emit = on_progress or (lambda k, d: None)
        ws = Path(ws)
        if kind == "review":
            time.sleep(self.pace)
            emit("model", "model call 1: 12,897 tokens in, 617 out, 47 s")
            task = (verbs.ctx.store.run(ref) or {}).get("task_id")
            name = ((verbs.ctx.store.task(task) or {}).get("name") or "") if task else ""
            if name == "vendor-scorecard":
                return enginemod.RunResult("FAIL - the score for Vendor C (7.4) does not match data/facts.json "
                                           "(7.1), and the pricing claim has no source in SOURCES.md.", 0, "", "")
            return enginemod.RunResult("PASS - every number matches data/facts.json and each claim has a source.",
                                       0, "", "")
        if session and session in self.step_of:          # a resume or a job's wake-up: same step as before
            step_n = self.step_of[session]
        else:
            step_n = int(prompt.split("STEP ", 1)[1].split(" ", 1)[0]) if "STEP " in prompt else 1
        sp = verbs.ctx.store.spec(verbs.ctx.store.run(ref)["task_id"], verbs.ctx.store.run(ref)["version"])
        plan = verbs.ctx.store.run_plan(ref) or (sp or {}).get("steps", [])     # the run's own steps, as expanded
        step = plan[step_n - 1] if step_n <= len(plan) else {"title": "", "outputs": []}
        step = {**step, "outputs": [speclib.fill(o, (sp or {}).get("params")) for o in step.get("outputs") or []]}
        sid = session or f"mock-{ref}-{step_n}-{int(time.time())}"
        self.step_of[sid] = step_n
        acts = _work(step["title"], step["outputs"])
        i = self.pos.get(sid, 0)
        repeats = 0
        while i < len(acts):
            if stop():
                self.pos[sid] = i
                return enginemod.RunResult("", enginemod.CANCELLED, "", sid)
            if park.requested() or permissions.pending(ref):
                self.pos[sid] = i
                return enginemod.RunResult("", enginemod.PARKED, "", sid)
            time.sleep(self.pace)
            k, d = acts[i]
            i += 1
            if k == "job":
                jobs.submit(ref, f'"{sys.executable}" -c "import time; [print(f\'row {{n}}\', flush=True) or '
                                 f'time.sleep(0.4) for n in range(8)]"', str(ws), why="fetch the raw data and write "
                                 "data/facts.json", after="check data/facts.json", expects=["data/facts.json"])
                (ws / "data").mkdir(parents=True, exist_ok=True)
                (ws / "data" / "facts.json").write_text('{"close": 279.05, "low_3m": {"value": 264.22}}',
                                                        encoding="utf-8")
                emit("tool", "submitted a job: python scripts/facts.py")
                self.pos[sid] = i
                return enginemod.RunResult("JOB SUBMITTED", 0, "", sid)
            emit(k, d)
            if d == (acts[i - 2][1] if i >= 2 else None):
                repeats += 1
                if repeats == 4:
                    emit("looping", f"it is repeating the same 1 tool call(s) 5+ times: {d}. It is not stopped: "
                                    "park and steer it, or cancel it")
            run = verbs.ctx.store.run(ref) or {}
            name = (verbs.ctx.store.task(run.get("task_id")) or {}).get("name", "")
            if name == "dependency-audit" and step_n == 2 and i == 2 and not permissions.is_approved(
                    ref, "commands", r"\bgit\s+push\b"):
                permissions.ask(ref, "commands", "git push origin main", r"\bgit\s+push\b")
                emit("tool", "ran: git push origin main (waiting for your OK)")
                self.pos[sid] = i
                return enginemod.RunResult("WAITING FOR THE PERSON", enginemod.PARKED, "", sid)
        for o in step["outputs"]:
            p = ws / o
            p.parent.mkdir(parents=True, exist_ok=True)
            if o in ("PLAN.md", "OUTLINE.md"):          # a plan the next step repeats over (each:)
                p.write_text(f"# {o}\n\n## Steps\n" + "".join(f"{n}. {s}\n" for n, s in enumerate(MOCK_PLAN, 1)),
                             encoding="utf-8")
            elif o == "CHECK.md":
                p.write_text("# Check\n\n- ran the commands in PLAN.md: all pass\n\nRESULT: PASS\n", encoding="utf-8")
            elif step.get("item"):                       # one planned item: add its section
                with p.open("a", encoding="utf-8") as f:
                    f.write(f"\n## {step['item'].split(':')[0]}\n\nWritten by the mock worker (step {step_n}).\n")
            elif not p.exists():
                p.write_text(f"# {o}\n\nWritten by the mock worker for step {step_n}.\n\nVERIFIED: 4 claims checked\n",
                             encoding="utf-8")
        self.pos.pop(sid, None)
        return enginemod.RunResult(f"Step {step_n} done: wrote {', '.join(step['outputs']) or 'nothing'}.", 0, "", sid)


# ---------- scripted orchestrator ----------

class MockOrchestrator:
    """Answers from the store, without a model, and shows its work the way the real one does. It starts a run only
    when told to ("start <task>"), and fills a draft's missing parameters from what the person says."""
    def __init__(self, pace=0.8):
        self.pace = pace

    def turn(self, ref, message, store, flows, catalog, broker, draft=None):
        note = lambda d: store.event(ref, "orchestrator", d)
        time.sleep(self.pace)
        note("model call 1: 2 s, 1 tool call(s)")
        text = message.strip()
        low = text.lower()
        d = draft or (store.draft(ref) if ref.startswith("d") else None)
        if d:
            view = verbs._draft_view(d)
            sp = dict(d["spec"])
            missing = [k for k in (d["asks"] or {}) if not str((sp.get("params") or {}).get(k, "")).strip()]
            if missing:
                sp["params"] = {**(sp.get("params") or {}), missing[0]: text}
                note(f"called draft_update {{\"param\": \"{missing[0]}\"}}")
                store.draft_set(d["id"], sp)
                view = verbs._draft_view(store.draft(d["id"]))
            time.sleep(self.pace)
            note("model call 2: 3 s, 0 tool call(s)")
            left = view["problems"]
            return ("(mock orchestrator) Noted. " + ("Still missing: " + "; ".join(left) if left
                                                     else "The definition is complete; sign it when it looks right."))
        names = [t["name"] for t in verbs.call("tasks")]
        target = next((n for n in names if n in low), None)
        if target and any(w in low for w in ("start", "run ", "rerun", "kick off")):
            note(f'called run {{"task": "{target}"}}')
            r = verbs.call("run", task=target)
            time.sleep(self.pace)
            note("model call 2: 2 s, 0 tool call(s)")
            return f"(mock orchestrator) Started {target}: run {r['id']} is {r['status']}."
        note('called runs {"live": true}')
        live = verbs.call("runs", live=True)
        time.sleep(self.pace)
        note("model call 2: 3 s, 0 tool call(s)")
        if not live:
            return "(mock orchestrator) Nothing is running. Say \"start <task>\" to run one: " + ", ".join(names) + "."
        lines = []
        for r in live[:4]:
            p = verbs.call("progress", run=r["id"], recent=0)
            lines.append(f"{r['task']} is {r['status']} at step {r['step']} of {r['steps_total']}"
                         + (f"; last: {p['last_activity'].split(': ', 1)[-1]}" if p["last_activity"] else "")
                         + (f"; it asks: {r['ask']['text']}" if r.get("ask") else ""))
        return "(mock orchestrator) " + " ".join(s + "." for s in lines)


# ---------- seeding ----------

def _spec(flows, flow, name, ws, steps, goal, trigger=None, gates=()):
    sp = {"name": name, "flow": flow, "goal": goal, "workspace": str(ws), "steps": steps, "gates": list(gates),
          "trigger": trigger or {"kind": "manual"}, "retries": 1}
    return speclib.validate(sp, flows)


def seed(store, flows, root):
    """Tasks, drafts and finished runs in every state the UI has to show."""
    ws = lambda n: root / "work" / n
    inv = flows["investigation"]
    sp, _ = speclib.from_template(inv, name="googl-daily", workspace=str(ws("googl")))
    sp["params"] = {"question": "How did GOOGL move over the last 3 months, and what do the indicators say?",
                    "must_contain": "1- and 3-month change, 20/50-day averages, RSI, a verdict", "within_days": "14"}
    sp["trigger"] = {"kind": "cron", "cron": "0 7 * * 1-5"}
    for st in sp["steps"]:
        st["gate"] = None                       # the mock checks only what the mock worker can satisfy
    googl, _ = store.sign(speclib.validate(sp, flows))

    sp2, _ = speclib.from_template(inv, name="competitor-scan", workspace=str(ws("competitors")))
    sp2["params"] = {"question": "What did our three main competitors ship in the last month?",
                     "must_contain": "a dated list per competitor with sources", "within_days": "31"}
    for st in sp2["steps"]:
        st["gate"] = None
    sp2["gates"] = [{"type": "review", "text": "Every item has a dated, primary source"}]
    scan, _ = store.sign(speclib.validate(sp2, flows))

    audit, _ = store.sign(_spec(flows, "coding", "dependency-audit", ws("audit"), [
        {"title": "Plan the upgrade", "instruction": "List outdated dependencies in PLAN.md.", "outputs": ["PLAN.md"],
         "tools": ["file", "terminal"]},
        {"title": "Upgrade and push", "instruction": "Upgrade, run the tests, push the branch.",
         "outputs": ["CHANGES.md"], "tools": ["file", "terminal"]}],
        "Dependencies are current and the tests pass"))

    notes, _ = store.sign(_spec(flows, "content", "release-notes", ws("notes"), [
        {"title": "Collect the changes", "instruction": "List merged changes in CHANGES.md.",
         "outputs": ["CHANGES.md"], "tools": ["file"]},
        {"title": "Write the notes", "instruction": "Write RELEASE.md for users.", "outputs": ["RELEASE.md"],
         "tools": ["file"]},
        {"title": "Loop check", "instruction": "Build the notes page.", "outputs": ["page.html"], "tools": ["file"]}],
        "RELEASE.md tells users what changed", trigger={"kind": "cron", "cron": "30 16 * * 5"}))

    score, _ = store.sign(_spec(flows, "investigation", "vendor-scorecard", ws("vendors"), [
        {"title": "Gather sources", "instruction": "Collect vendor sources into SOURCES.md.",
         "outputs": ["SOURCES.md"], "tools": ["file", "web"]},
        {"title": "Compute the facts", "instruction": "Score vendors into data/facts.json.",
         "outputs": ["data/facts.json"], "tools": ["file", "terminal", "jobs"]},
        {"title": "Write the report", "instruction": "Write REPORT.md.", "outputs": ["REPORT.md"], "tools": ["file"]}],
        "REPORT.md ranks the vendors with sources",
        gates=[{"type": "review", "text": "Every score matches data/facts.json and every claim has a source"}]))

    store.task_set(store.task_by_name("dependency-audit")["id"], scheduled=0)
    # history: finished runs in each end state
    now = time.time()
    for tid, status, ago, err in ((googl, "done", 86400, ""), (googl, "done", 2 * 86400, ""),
                                  (googl, "needs_you", 3 * 86400, "task gates failing:\n[review] Every number and "
                                   "factual claim in REPORT.md has a source listed in SOURCES.md: FAIL - the 3-month "
                                   "low is a close ($265.29), data/prices.csv shows the low was $264.22"),
                                  (googl, "cancelled", 4 * 86400, "cancelled by you"),
                                  (scan, "done", 5 * 86400, ""), (notes, "failed", 6 * 86400,
                                   "step 2 (Write the notes) failed: the worker run failed (exit 1)")):
        rid = store.run_new(tid, "schedule (weekdays at 07:00)" if tid == googl else "manual")
        sp_t = store.spec(tid)
        last = len(sp_t["steps"]) if status in ("done", "needs_you") else 2
        for n in range(1, last + 1):
            store.step_set(rid, n, 1, model=sp_t["steps"][n - 1]["model"], status="passed" if n < last or
                           status == "done" else ("failed" if status == "failed" else "passed"),
                           started=now - ago + n * 240, ended=now - ago + n * 240 + 200,
                           report=f"Step {n}: wrote {', '.join(sp_t['steps'][n - 1]['outputs'])}.", gate="passed")
        store.run_set(rid, status=status, started=now - ago, ended=now - ago + last * 240 + 200, step=last,
                      error=err, result="REPORT.md written and verified." if status == "done" else "")
        store.event(rid, "end", status + (f": {err[:200]}" if err else ""))
    # a content task from its template: an outline, then one step per section (each:), then assemble and check
    gsp, _ = speclib.from_template(flows["content"], name="ga-study-guide", workspace=str(ws("ga-guide")))
    gsp["params"] = {"piece": "a study guide for the CS6515 cumulative final, for a student revising",
                     "output": "GUIDE.md", "sources": "refs/LINKS.md"}
    for st in gsp["steps"]:
        st["gate"] = None                       # the mock checks only what the mock worker can satisfy
    guide, _ = store.sign(speclib.validate(gsp, flows))

    # drafts: one nearly ready, one just begun
    d1sp, asks = speclib.from_template(inv, name="rates-outlook", workspace=str(ws("rates")))
    d1sp["params"] = {"question": "Where are US mortgage rates heading over the next quarter?"}
    d1 = store.draft_new("investigation", d1sp, asks, source="front")
    store.message(d1, "person", "Where are US mortgage rates heading over the next quarter?")
    store.message(d1, "orchestrator", "(mock orchestrator) What must a good answer contain, and how far back may "
                                      "sources go?")
    # the way every front starts one: the `draft` verb (what you typed answers the template's first question)
    verbs.call("draft", text="Add CSV export to the hiking app's member list", flow="coding")
    return {"googl": googl, "scan": scan, "audit": audit, "notes": notes, "score": score, "guide": guide}


# ---------- the loop ----------

class MockEngine:
    """The real engine with the mock worker, in a thread; keeps something running."""
    def __init__(self, store, flows, broker, tasks, idle_s=25):
        self.eng = enginemod.Engine(store, flows, broker, step_runner=MockWorker(),
                                    job_runner=lambda j, db, **kw: jobs.run(j, db, unload=lambda: True, poll=0.2, **kw))
        self.store, self.tasks, self.idle_s = store, tasks, idle_s
        self.order = [tasks["guide"], tasks["scan"], tasks["audit"], tasks["notes"], tasks["score"], tasks["googl"]]
        self.i, self.quiet_since = 0, time.time()

    def loop(self):
        while True:
            try:
                if self.eng.run_once():
                    self.quiet_since = time.time()
                    continue
                if not self.store.runs(live=True) and time.time() - self.quiet_since > self.idle_s:
                    tid = self.order[self.i % len(self.order)]
                    self.i += 1
                    self.store.run_new(tid, "mock loop")
                    self.quiet_since = time.time()
            except Exception as e:      # a mock must never die quietly; say why and go on
                print(f"mock engine: {type(e).__name__}: {e}", flush=True)
            time.sleep(1)


def build(root=None):
    """Store, flows, broker and the verbs context for a mock session; returns (ctx, engine)."""
    root = Path(root or paths.STATE)
    root.mkdir(parents=True, exist_ok=True)
    flows = flowlib.load_flows()
    store = durable.Store()
    broker = Broker(root / "machine-mock.db", server=FakeServer(), poll=0.2)
    ctx = verbs.Ctx(store=store, flows=flows, broker=broker, orchestrator=MockOrchestrator())
    verbs.ctx = ctx
    tasks = seed(store, flows, root)
    for t in ("scan", "audit", "notes"):
        store.run_new(tasks[t], "manual")
    return ctx, MockEngine(store, flows, broker, tasks)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8918
    ctx, eng = build()
    threading.Thread(target=eng.loop, name="mock-engine", daemon=True).start()
    from .server import app as appmod
    import uvicorn
    print(f"Ariadne (mock backend, state in {paths.STATE}): http://127.0.0.1:{port}", flush=True)
    uvicorn.run(appmod.create_app(ctx, start_worker=False), host="127.0.0.1", port=port, log_level="warning",
                timeout_graceful_shutdown=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
