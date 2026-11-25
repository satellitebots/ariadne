"""The engine: runs durable tasks, one worker per step, through the broker (docs/DESIGN.md, "Workers").

A run executes its task's signed version step by step. Each step is one headless Hermes run with the step's own
instruction, tools, inputs (the files earlier steps left) and gate; steps hand over through files, not conversation.
Around every step the engine holds the broker's lease: it yields at step boundaries when someone waits, switches the
model when the next step needs other weights, hands the whole machine to jobs, and gives it back when parked.

Nothing here is a chatbot: no gateway, no persona, no memory of its own. Model-free to test: `step_runner`,
`job_runner`, `kv` and the broker's server are all injectable.
"""
import json
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import durable, flows as flowlib, jobs, park, paths, spec as speclib

PARKED = 125      # a run stopped at a boundary by a park request
TURNS = 126       # out of turns (not failure: the check decides)
CANCELLED = 130


@dataclass
class RunResult:
    text: str
    exit_code: int
    log: str
    session_id: str = ""     # the Hermes session the run used (printed by -Q)


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_SESSION_ID = re.compile(r"session_id:\s*(\S+)")


def _clean_output(out):
    """Hermes -Q prints tool previews (boxed, coloured diffs), the answer, then session info; keep the answer."""
    lines = []
    for l in _ANSI.sub("", out or "").splitlines():
        if re.match(r"^\s*(session[ _]?id|session:|resume with)", l, re.I) or l.lstrip().startswith("│"):
            continue
        lines.append(l)
    return "\n".join(lines).strip()


def _kill_tree(p):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        p.kill()


def _latest_session(home, since):
    """The Hermes session a killed run was writing (its id is only printed at a clean exit)."""
    try:
        c = sqlite3.connect(str(Path(home) / "state.db"), timeout=10)
        r = c.execute("SELECT id FROM sessions WHERE started_at >= ? ORDER BY started_at DESC LIMIT 1",
                      (since - 2,)).fetchone()
        c.close()
        return r[0] if r else ""
    except sqlite3.Error:
        return ""


def stop_gateway(home):
    """Stop a Hermes gateway left running in a worker home (older workers started them; headless runs do not)."""
    if not (Path(home) / "gateway.pid").exists():
        return
    subprocess.run([str(paths.HERMES_EXE), "gateway", "stop", "--yes"], env=dict(os.environ, HERMES_HOME=str(home)),
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=120)

STEP_PROMPT = """You are a worker of Ariadne. You do ONE step of a signed task, then stop.

TASK GOAL: {goal}
WORKSPACE: {workspace}   (the terminal is bash: write paths with forward slashes, e.g. {workspace_posix})

STEP {n} of {total}: {title}
{instruction}

FILES FROM EARLIER STEPS (read what you need): {inputs}
THIS STEP MUST LEAVE: {outputs}
HOW IT IS CHECKED: {gate}
{steering}{retry}
Rules:
- Do this step only. Later steps are not yours.
- Search with web_search (limit 3-5); read a page with web_fetch. Keep only what the step needs from each.
- Heavy or long work (installs, downloads, data pulls, builds, full test suites) is a job: write a script, call
  submit_job, then reply 'JOB SUBMITTED: <id>' and stop. You are woken here with the result.
- If the step cannot be done as written, reply starting with 'OFF-PLAN:' and the reason.
- Finish with a short report: what you did, which files you left, how you checked them.
"""

RETRY = """
THIS IS ATTEMPT {attempt}. The last attempt failed its check:
{reasons}
Fix exactly that; keep what was already right.
"""

STEERING = """
STEERING FROM THE PERSON (follow it; where it conflicts with the step, the person wins):
- {notes}
"""

RESUME_PROMPT = ("You were paused at a step boundary. Continue the same step where you left off. If your last tool "
                 "call has no result, run it again; re-read a file before editing it.")

JOB_RESULT_PROMPT = """You were unloaded while Ariadne ran the job(s) you submitted. Results:

{results}

Continue the step from here: fix and resubmit if a job failed (resume, do not start over), otherwise finish the step."""

REVIEW_PROMPT = """You are Ariadne's reviewer. Check one claim about the workspace ({workspace}) with your read tools; change
nothing. Be strict: it passes only if you saw the evidence yourself.

TASK GOAL: {goal}
CHECK: {check}

Reply with exactly one line: PASS - <evidence>   or   FAIL - <what is missing or wrong>"""


# ---------- one Hermes run for one step ----------

def hermes_step(flow, kind, prompt, workspace, ref, model, tools, session=None, budget=1800, turns=60,
                stop=lambda: False):
    """One headless Hermes run. kind: "step" (the step's tools) or "review" (read-only, file tools only).

    Returns RunResult; exit 125 when parked at a boundary, 130 when cancelled, 124 out of time, 126 out of turns.
    """
    home = flow.home
    home.mkdir(parents=True, exist_ok=True)
    (home / "ariadne_phase").write_text("plan" if kind == "review" else "execute", encoding="utf-8")
    (home / "ariadne_task").write_text(ref, encoding="utf-8")           # jobs_mcp records jobs against the run
    (home / "ariadne_workspace").write_text(str(workspace), encoding="utf-8")
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    qfile = paths.LOGS / f"{ref}-{kind}-{int(time.time())}.prompt.md"
    qfile.write_text(prompt, encoding="utf-8")
    hermes_sets = [t for t in tools if t not in flow.mcp_servers]
    mcp_sets = [f"mcp-{t}" for t in tools if t in flow.mcp_servers]
    cmd = [str(paths.HERMES_EXE), "chat", "--query-file", str(qfile), "-Q", "--source", "tool"]
    if session:
        cmd += ["--resume", session, "--no-restore-cwd"]
    else:
        cmd += ["--run-budget", str(budget), "--max-turns", str(turns), "-t", ",".join(hermes_sets + mcp_sets)]
        for s in flow.skills + flow.shared_skills:
            cmd += ["-s", s]
        if model:
            cmd += ["-m", model]
        if flow.reasoning.get("execute") and kind == "step":
            cmd += ["--reasoning", flow.reasoning["execute"]]
    env = dict(os.environ, HERMES_HOME=str(home), PYTHONIOENCODING="utf-8")
    log = qfile.with_suffix("").with_suffix(".log")
    started = time.time()
    p = subprocess.Popen(cmd, cwd=workspace, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    boundary = park.StepBoundary(home)
    stdout = stderr = ""
    while True:
        try:
            stdout, stderr = p.communicate(timeout=3)
            code = p.returncode
            break
        except subprocess.TimeoutExpired:
            pass
        if time.time() > started + budget + 180:
            _kill_tree(p)
            stdout, stderr = p.communicate()
            code = 124
            break
        if stop() or (park.requested() and kind == "step"):
            if boundary.reached():          # let the call in flight finish, then stop at that boundary
                _kill_tree(p)
                stdout, stderr = p.communicate()
                code = CANCELLED if stop() else PARKED
                break
        else:
            boundary.pos = None
    out = (stdout or "") + ("\n[stderr]\n" + stderr if (stderr or "").strip() else "")
    log.write_text(" ".join(cmd) + "\n\n" + out, encoding="utf-8")
    sid = _SESSION_ID.findall(out) or ([session or _latest_session(home, started)] if code in (PARKED, CANCELLED) else [])
    return RunResult(_clean_output(stdout), code, str(log), sid[-1] if sid and sid[-1] else "")


# ---------- the engine ----------

class Engine:
    def __init__(self, store=None, flows=None, broker=None, step_runner=None, job_runner=None, kv=None,
                 clock=time.time, wait_resumed=None, checks_timeout=600):
        from . import broker as brokerlib
        self.store = store or durable.Store()
        self.flows = flows or flowlib.load_flows()
        self.broker = broker or brokerlib.default()
        real = step_runner is None
        self.step_runner = step_runner or hermes_step
        self.job_runner = job_runner or (jobs.run if real else (lambda j, db: jobs.run(j, db, unload=lambda: True,
                                                                                            poll=0.05)))
        if kv is None:
            from . import kvcache
            kv = kvcache.default() if real else kvcache.NoKVCache()
        self.kv = kv
        self.now = clock
        self.wait_resumed = wait_resumed or park.wait_resumed
        self.checks_timeout = checks_timeout

    # ---------- the scheduler ----------
    def sweep(self):
        """Queue a run for every task whose trigger is due; move its next due time on. A machine that was off runs a
        missed schedule once, not once per miss."""
        now = self.now()
        queued = []
        for t in self.store.due(now):
            sp = self.store.spec(t["id"])
            if any(r["status"] in durable.LIVE for r in self.store.runs(t["id"], live=True)):
                self.store.event(t["id"], "schedule", "due, but a run is still live; skipped this time")
            else:
                queued.append(self.store.run_new(t["id"], f"schedule ({speclib.describe_trigger(sp)})"))
            self.store.task_set(t["id"], next_due=speclib.next_due(sp, now))
        return queued

    def run_once(self):
        """Sweep the schedules, then execute the oldest queued run. Returns True if a run was executed."""
        self.sweep()
        r = self.store.claim()
        if not r:
            return False
        try:
            self.execute(r)
        except Exception as e:      # never leave a run live with no one behind it
            self.store.run_set(r["id"], status="failed", error=f"{type(e).__name__}: {e}", ended=self.now())
            self.store.event(r["id"], "error", f"{type(e).__name__}: {e}")
        return True

    # ---------- one run ----------
    def execute(self, r):
        rid = r["id"]
        sp = self.store.spec(r["task_id"], r["version"])
        flow = self.flows.get(sp["flow"])
        if not flow:
            return self._end(rid, "failed", error=f"flow {sp['flow']} no longer exists")
        ws = Path(sp["workspace"])
        ws.mkdir(parents=True, exist_ok=True)
        steps = sp["steps"]
        first = steps[r["step"] - 1] if r["step"] else steps[0]
        self.store.event(rid, "machine", self.broker.describe())
        lease = self.broker.acquire("worker", rid, first["model"],
                                    on_wait=lambda s: self.store.event(rid, "waiting", self.broker.describe()))
        try:
            self.store.run_set(rid, status="running", started=r["started"] or self.now())
            started = self.now()
            for step in steps[(r["step"] or 1) - 1:]:
                if self._cancelled(rid):
                    return self._end(rid, "cancelled", "cancelled by you")
                if self.now() - started > sp["budget_s"]:
                    return self._end(rid, "timed_out", error=f"the run used its {sp['budget_s']} s; the work so far "
                                                               "is in the workspace")
                if step["n"] > 1 and lease.boundary():
                    self.store.event(rid, "machine", f"yielding at the boundary before step {step['n']}: "
                                                     + self.broker.describe())
                    self.store.run_set(rid, status="waiting")
                    lease.yield_turn(note=f"step {step['n']}")
                    self.store.run_set(rid, status="running")
                if lease.model != step["model"]:
                    lease.switch(step["model"])
                self.store.run_set(rid, step=step["n"])
                outcome = self._step(rid, sp, flow, ws, step, lease)
                if outcome != "passed":
                    return outcome
            failures = self._gates(rid, sp, flow, ws, sp["gates"], lease)
            if failures:
                self.store.event(rid, "gates", "task gates failing:\n" + "\n".join(failures))
                return self._end(rid, "needs_you", error="task gates failing:\n" + "\n".join(failures))
            self.store.event(rid, "gates", f"passed ({len(sp['gates'])} task gate(s))")
            return self._end(rid, "done", result=self._reports(rid))
        finally:
            lease.release()

    def _step(self, rid, sp, flow, ws, step, lease):
        """Run one step to a passing check, retrying with the reasons. Returns "passed" or the run's end status."""
        n, total = step["n"], len(sp["steps"])
        retry_text, session = "", None
        for attempt in range(1, sp["retries"] + 2):
            notes = self.store.take_steers(rid)
            prompt = STEP_PROMPT.format(
                goal=speclib.fill(sp["goal"], sp["params"]), workspace=ws, workspace_posix=Path(ws).as_posix(),
                n=n, total=total, title=step["title"], instruction=speclib.fill(step["instruction"], sp["params"]),
                inputs=", ".join(o for s in sp["steps"][:n - 1] for o in s["outputs"]) or "none",
                outputs=", ".join(step["outputs"]) or "nothing in particular; report what you did",
                gate=_gate_text(step["gate"], sp["params"]),
                steering=STEERING.format(notes="\n- ".join(notes)) if notes else "", retry=retry_text)
            if notes:
                self.store.event(rid, "steer", f"{len(notes)} note(s) delivered to step {n}")
            self.store.step_set(rid, n, attempt, model=step["model"], status="running")
            self.store.event(rid, "step", f"{n}/{total} {step['title']} on {step['model']}, attempt {attempt}")
            r = self._runner(rid, flow, "step", prompt, ws, step, session=None)
            r = self._settle(rid, flow, ws, step, r, lease)
            if r.exit_code == CANCELLED:
                return self._end(rid, "cancelled", "cancelled by you")
            self.store.step_set(rid, n, attempt, log=r.log, session=r.session_id, report=r.text[-6000:])
            if r.text.lstrip().upper().startswith("OFF-PLAN"):
                self.store.step_set(rid, n, attempt, status="off-plan", ended=self.now())
                return self._end(rid, "needs_you", error=f"step {n} says the definition is wrong: {r.text[:1500]}")
            if r.exit_code not in (0, 124, TURNS):
                reasons = [f"the worker run failed (exit {r.exit_code}); log {r.log}"]
            else:
                if r.exit_code:
                    self.store.event(rid, "step", f"{n}: {'time' if r.exit_code == 124 else 'turns'} used up; "
                                                  "keeping what it wrote and checking")
                reasons = self._outputs_missing(ws, step) + self._gates(rid, sp, flow, ws, [step["gate"]] if step["gate"]
                                                                         else [], lease)
            if not reasons:
                self.store.step_set(rid, n, attempt, status="passed", ended=self.now(), gate="passed")
                self.store.event(rid, "step", f"{n}/{total} passed")
                return "passed"
            self.store.step_set(rid, n, attempt, status="failed", ended=self.now(), gate="\n".join(reasons)[:4000])
            self.store.event(rid, "step", f"{n}/{total} failed its check: {reasons[0][:300]}")
            retry_text = RETRY.format(attempt=attempt + 1, reasons="\n".join(reasons))
        return self._end(rid, "needs_you", error=f"step {n} ({step['title']}) still fails after {sp['retries'] + 1} "
                                                 f"attempt(s):\n" + "\n".join(reasons))

    def _runner(self, rid, flow, kind, prompt, ws, step, session):
        budget = int(flow.run_budget.get("execute", 1800))
        turns = int(flow.max_turns.get("execute", 60))
        tools = step["tools"] if kind == "step" else ["file"]
        return self.step_runner(flow, kind, prompt, str(ws), rid, step["model"], tools, session=session,
                                budget=budget, turns=turns, stop=lambda: self._cancelled(rid))

    def _settle(self, rid, flow, ws, step, r, lease):
        """Handle what a step run can come back with before it is checked: a park (hold, then resume the same
        session) and submitted jobs (unload, run, wake the same session with the results). Loops until neither."""
        title = rid
        scope = f"step-{step['n']}"
        for _ in range(40):
            self.kv.save(title, step["model"], scope)
            if r.exit_code == PARKED:
                self.store.run_set(rid, status="parked")
                self.store.event(rid, "park", f"stopped at a boundary in step {step['n']}; the machine is free. "
                                              "Steer it, then resume.")
                park.mark_parked(rid, step["model"])
                lease.release()
                self.wait_resumed()
                if self._cancelled(rid):
                    return RunResult(r.text, CANCELLED, r.log, r.session_id)
                again = self.broker.acquire("worker", rid, step["model"], note="resuming after park")
                lease.held, lease.model = True, again.model
                self.store.run_set(rid, status="running")
                notes = self.store.take_steers(rid)
                prompt = (STEERING.format(notes="\n- ".join(notes)) + "\n" if notes else "") + RESUME_PROMPT
                self.store.event(rid, "park", "resumed" + (f" with {len(notes)} steering note(s)" if notes else ""))
                self.kv.restore(title, step["model"], scope)
                r = self._runner(rid, flow, "step", prompt, ws, step, session=r.session_id or None)
                continue
            pending = jobs.for_task(rid, "pending", self.store_jobs_db())
            if not pending or r.exit_code != 0:
                return r
            results = []
            lease.switch(None, kind="job")
            for j in pending:
                self.store.event(rid, "job", f"{j['id']} started: {j['why'] or j['command']} (models unloaded)")
                j = self.job_runner(j, self.store_jobs_db())
                res = json.loads(j.get("result") or "{}")
                self.store.event(rid, "job", f"{j['id']} {j['status']}: exit {j['exit_code']} in {res.get('seconds')} s")
                results.append(jobs.result_text(j))
            lease.switch(step["model"], kind="worker")
            self.kv.restore(title, step["model"], scope)
            r = self._runner(rid, flow, "step", JOB_RESULT_PROMPT.format(results="\n\n".join(results)), ws, step,
                             session=r.session_id or None)
        return r

    def store_jobs_db(self):
        return None   # jobs live in jobs.py's own table (paths.TASKS_DB), where jobs_mcp records them

    def _outputs_missing(self, ws, step):
        return [f"{o} is missing (the step must leave it)" for o in step["outputs"] if not (Path(ws) / o).exists()]

    def _gates(self, rid, sp, flow, ws, gates, lease):
        """Command gates run in the workspace; review gates go to a read-only reviewer run. Returns the failures."""
        failures = []
        for g in gates:
            text = speclib.fill(g["text"], sp["params"])
            if g["type"] == "run":
                try:
                    p = subprocess.run(text, shell=True, cwd=ws, capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=self.checks_timeout)
                    if p.returncode != 0:
                        failures.append(f"$ {text}\n(exit {p.returncode})\n{(p.stdout + p.stderr)[-2000:]}")
                except subprocess.TimeoutExpired:
                    failures.append(f"$ {text}\n(timed out after {self.checks_timeout} s)")
                continue
            model = sp["steps"][-1]["model"]
            if lease.model != model:
                lease.switch(model)
            r = self._runner(rid, flow, "review", REVIEW_PROMPT.format(workspace=ws, goal=speclib.fill(
                sp["goal"], sp["params"]), check=text), ws, {"model": model, "tools": ["file"]}, session=None)
            verdict = next((l.strip() for l in r.text.splitlines() if re.match(r"\s*(PASS|FAIL)\b", l)), "")
            if not verdict.upper().startswith("PASS"):
                failures.append(f"[review] {text}: {verdict or 'no verdict'}")
        return failures

    def _cancelled(self, rid):
        return (self.store.run(rid) or {}).get("error") == "cancel requested"

    def _reports(self, rid):
        last = {}
        for st in self.store.steps(rid):
            last[st["n"]] = st["report"]
        return "\n\n".join(f"Step {n}:\n{t}" for n, t in sorted(last.items()) if t)

    def _end(self, rid, status, result="", error=""):
        self.store.run_set(rid, status=status, ended=self.now(), result=result or self._reports(rid), error=error)
        self.store.event(rid, "end", status + (f": {error[:300]}" if error else ""))
        self.kv.drop(rid)
        return status


def _gate_text(g, params):
    if not g:
        return "the step's outputs must exist"
    return ("this command must exit 0 in the workspace: " if g["type"] == "run" else "a reviewer checks: ") + \
        speclib.fill(g["text"], params)
