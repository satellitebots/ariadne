"""Task orchestrator: every task, from any source, goes through here.

    brief -> route (router model picks the flow) -> plan (Hermes worker, read-only tools)
          -> backbrief (sent back to whoever gave the task) -> sign-off (approve / revise / cancel)
          -> execute (Hermes worker, the flow's full toolset) -> checks (retry once) -> report

One worker process (`python -m ariadne.orchestrator serve`) does all the runs, one at a time, so only one model
is ever on the GPU. Tasks live in .ariadne/tasks.db; MCP servers and the CLI only read and write that table and
make sure the worker is running. Every task and its outcome is recorded in the shared memory.
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import flows as flowlib
from . import jobs, llm, park, paths, protocol, render
from .memory import Memory, format_hits

FINAL = ("done", "failed", "cancelled", "rejected", "timed_out")   # a caller is waiting and the task is over
WAITING = ("awaiting_gates", "awaiting_signoff", "needs_attention")   # the task needs the person who gave it
GATES_QUESTION = ("Before this task starts: what are the check gates? List how we will know it is done, end to "
                  "end - commands that must pass (`run: pytest -q`) and outcomes a reviewer can verify (\"README "
                  "explains every command\"). Answer with set_gates / `task gates ID ...`.")
GATES_HEAD = re.compile(r"^\s*#*\s*(check gates|gates|checks|done when|acceptance criteria|acceptance|qa)\s*:?\s*(.*)$", re.I)


def parse_gates(text):
    """Gates from a brief: the lines under a 'Gates:' / 'Checks:' / 'Done when:' / 'Acceptance:' heading (bullets or
    one line). `run: <cmd>` or a `backticked command` is a command gate; anything else is a review gate."""
    gates, on = [], False
    for line in (text or "").splitlines():
        m = GATES_HEAD.match(line)
        if m:
            on = True
            if m.group(2).strip():
                gates.append(gate(m.group(2)))
            continue
        if not on:
            continue
        s = line.strip()
        if not s:
            on = not gates          # a blank line ends the section once it has gates
            continue
        if re.match(r"^([-*]|\d+[.)])\s+", s) or not re.match(r"^[A-Za-z][\w ]{0,40}:\s*$", s):
            gates.append(gate(re.sub(r"^([-*]|\d+[.)])\s*", "", s)))
        else:
            on = False              # the next heading
    return gates


def gate(item):
    item = item.strip()
    m = re.match(r"^(run|cmd|command)\s*:\s*(.+)$", item, re.I) or re.match(r"^`([^`]+)`\s*(?:passes|succeeds)?\.?$", item)
    if m:
        return {"type": "run", "text": (m.group(2) if m.lastindex == 2 else m.group(1)).strip().strip("`")}
    return {"type": "review", "text": item}


def gates_text(gates):
    return "\n".join(f"G{i}. [{g['type']}] {g['text']}" for i, g in enumerate(gates, 1))
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, created REAL, updated REAL, source TEXT, text TEXT, workspace TEXT, flow TEXT,
  status TEXT, plan TEXT DEFAULT '', feedback TEXT DEFAULT '', result TEXT DEFAULT '', error TEXT DEFAULT '',
  models TEXT DEFAULT '', session TEXT DEFAULT '', learn INTEGER DEFAULT 0, gates TEXT DEFAULT '',
  model TEXT DEFAULT '', plan_json TEXT DEFAULT '', run_started REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(task_id TEXT, ts REAL, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  name TEXT PRIMARY KEY, created REAL, updated REAL, source TEXT DEFAULT '',
  segment INTEGER DEFAULT 1, flow TEXT DEFAULT '', summary TEXT DEFAULT '',
  fresh INTEGER DEFAULT 0, dirty INTEGER DEFAULT 0, hermes_id TEXT DEFAULT '');
"""


class TaskError(ValueError):
    pass


class Store:
    def __init__(self, db_path=None, require_gates=True):
        self.db_path = str(db_path or paths.TASKS_DB)
        self.require_gates = require_gates  # no task starts without check gates (tests of other parts turn it off)
        if db_path is None:
            paths.ensure()
        with self._conn() as c:
            c.executescript(SCHEMA)
            have = [r["name"] for r in c.execute("PRAGMA table_info(tasks)")]
            for col in ("models", "session", "gates", "model", "plan_json"):
                if col not in have:
                    c.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT DEFAULT ''")
            if "learn" not in have:
                c.execute("ALTER TABLE tasks ADD COLUMN learn INTEGER DEFAULT 0")
            if "run_started" not in have:
                # The task's wall clock starts whenever the worker claims it (B1); old rows have no baseline.
                c.execute("ALTER TABLE tasks ADD COLUMN run_started REAL DEFAULT 0")
            if "hermes_id" not in [r["name"] for r in c.execute("PRAGMA table_info(sessions)")]:
                c.execute("ALTER TABLE sessions ADD COLUMN hermes_id TEXT DEFAULT ''")

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
        finally:
            c.close()

    def event(self, tid, kind, detail=""):
        with self._conn() as c:
            c.execute("INSERT INTO events VALUES (?,?,?,?)", (tid, time.time(), kind, str(detail)[:4000]))
        from .activity import log
        log(f"task {tid}", f"{kind}: {detail}")

    def submit(self, text, source="cli", workspace="", flow="", session="", gates=None, model=""):
        """session: a Hermes session to continue (the caller's conversation); default: one session per task.
        gates: the check gates (strings; `run: cmd` for commands) - else taken from the brief's Gates/Checks/Done when
        section. Without gates the task waits (awaiting_gates) and asks for them: nothing starts without them."""
        text = (text or "").strip()
        if not text:
            raise TaskError("the task text is empty")
        tid = time.strftime("t%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        now = time.time()
        session = (session or "").strip() or tid
        self.session(session, source)
        g = [gate(x) if isinstance(x, str) else x for x in (gates or [])] or parse_gates(text)
        status = "new" if g or not getattr(self, "require_gates", True) else "awaiting_gates"
        with self._conn() as c:
            c.execute("INSERT INTO tasks(id, created, updated, source, text, workspace, flow, status, session, gates, "
                      "result, model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (tid, now, now, source, text, workspace or "", flow or "", status, session, json.dumps(g),
                       "" if g else GATES_QUESTION, model or ""))
        self.event(tid, "brief", f"from {source}: {text[:300]}")
        self.event(tid, "gates", gates_text(g) if g else "none given: asked the person for them")
        return tid

    def set_gates(self, tid, gates):
        """Set or replace a task's check gates (list of strings, or text with one gate per line)."""
        if isinstance(gates, str):
            gates = parse_gates(gates) or [gate(re.sub(r"^\s*([-*]|\d+[.)])\s*", "", l)) for l in gates.splitlines() if l.strip().strip("-* ")]
        g = [gate(x) if isinstance(x, str) else x for x in gates if x]
        if not g:
            raise TaskError("no gates given")
        t = self.get(tid, events=False)
        if t["status"] == "awaiting_gates":
            self.update(tid, gates=json.dumps(g), status="new", result="")
        elif t["status"] in ("new", "awaiting_signoff", "needs_attention"):
            # New gates mean the approved plan may no longer satisfy them: plan again rather than execute blind.
            self.update(tid, gates=json.dumps(g), status="new")
        else:
            raise TaskError(f"task {tid} is '{t['status']}'; gates can change before execution only")
        self.event(tid, "gates", gates_text(g))

    # ---------- sessions ----------
    # An Ariadne session is a workstream: the tasks given in it, and a chain of Hermes sessions ("segments",
    # titled <name>~<n>). A checkpoint ends a segment with a handoff brief; the next segment starts from it.

    def session(self, name, source=""):
        """The session row, created on first use."""
        with self._conn() as c:
            r = c.execute("SELECT * FROM sessions WHERE name=?", (name,)).fetchone()
            if not r:
                now = time.time()
                c.execute("INSERT INTO sessions(name, created, updated, source) VALUES (?,?,?,?)",
                          (name, now, now, source))
                r = c.execute("SELECT * FROM sessions WHERE name=?", (name,)).fetchone()
        return dict(r)

    def session_update(self, name, **fields):
        fields["updated"] = time.time()
        with self._conn() as c:
            c.execute(f"UPDATE sessions SET {', '.join(f'{k}=?' for k in fields)} WHERE name=?", (*fields.values(), name))

    def sessions(self, limit=20):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT s.name, s.source, s.segment, s.flow, s.updated, substr(s.summary,1,200) AS summary, "
                "(SELECT count(*) FROM tasks t WHERE t.session=s.name) AS tasks FROM sessions s "
                "ORDER BY s.updated DESC LIMIT ?", (int(limit),))]

    def get(self, tid, events=True):
        with self._conn() as c:
            r = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            if not r:
                raise TaskError(f"no task {tid}")
            t = dict(r)
            if events:
                t["events"] = [f"{time.strftime('%H:%M:%S', time.localtime(e['ts']))} {e['kind']}: {e['detail']}"
                               for e in c.execute("SELECT * FROM events WHERE task_id=? ORDER BY ts", (tid,))]
        return t

    def list(self, limit=20):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, status, flow, source, substr(text,1,80) AS text, updated FROM tasks "
                "ORDER BY created DESC LIMIT ?", (int(limit),))]

    def update(self, tid, **fields):
        fields["updated"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), tid))

    def _transition(self, tid, allowed_from, to, **fields):
        t = self.get(tid, events=False)
        if t["status"] not in allowed_from:
            raise TaskError(f"task {tid} is '{t['status']}'; this needs one of {list(allowed_from)}")
        self.update(tid, status=to, **fields)

    def approve(self, tid, models=None):
        """Sign-off. models: {step number or 'all': model name} to change the plan's choices first. Approval locks
        the model plan: execution uses exactly these models, and fetches any that are not installed.
        Also re-approves a task that stopped for attention (a model failed to install, a tool was missing)."""
        t = self.get(tid, events=False)
        if t["status"] == "needs_attention" and (t.get("error") or "") == "off-plan":
            # The lifecycle's "stuck or off-plan -> backbrief" branch: the approved plan no longer fits, so the
            # person gets a new backbrief to sign off. Approving must not silently re-run the plan that failed.
            self._transition(tid, ("needs_attention",), "new", error="", result="")
            self.event(tid, "sign-off", "approved: planning again after an off-plan stop; a new backbrief follows")
            return
        mp = json.loads(t["models"]) if t.get("models") else None
        if models:
            if not mp:
                raise TaskError(f"task {tid} has no model plan to change")
            mp = apply_model_overrides(mp, models)
        fields = {"models": json.dumps(mp)} if mp else {}
        if mp:
            mp["locked"] = True
            fields["models"] = json.dumps(mp)
        self._transition(tid, ("awaiting_signoff", "needs_attention"), "approved", **fields)
        self.event(tid, "sign-off", "approved" + (f"; models locked: {model_summary(mp)}" if mp else ""))

    def revise(self, tid, feedback):
        t = self.get(tid, events=False)
        if t["status"] == "awaiting_gates":  # the answer to "what are the gates?"
            return self.set_gates(tid, feedback)
        fb = (t["feedback"] + "\n" if t["feedback"] else "") + feedback.strip()
        self._transition(tid, WAITING, "new", feedback=fb)
        self.event(tid, "sign-off", f"revise: {feedback[:300]}")

    def cancel(self, tid):
        self._transition(tid, ("new", "awaiting_gates", "awaiting_signoff", "approved", "needs_attention"), "cancelled")
        self.event(tid, "sign-off", "cancelled")

    def feedback(self, tid, text):
        """Feedback on a task at any time (after the report too). It stays open until a larger model folds it into
        a shared skill (save_skill with resolves=[task ids])."""
        text = (text or "").strip()
        if not text:
            raise TaskError("the feedback is empty")
        self.get(tid, events=False)
        self.event(tid, "feedback", text)
        with self._conn() as c:
            c.execute("UPDATE tasks SET learn=1 WHERE id=?", (tid,))

    def open_feedback(self):
        """Feedback not yet folded into a skill: [{task, flow, text, feedback}]."""
        with self._conn() as c:
            rows = c.execute("SELECT id, flow, substr(text,1,200) AS text FROM tasks WHERE learn=1").fetchall()
            out = []
            for r in rows:
                fb = [e["detail"] for e in c.execute("SELECT detail FROM events WHERE task_id=? AND kind IN "
                                                     "('feedback','checks','qa') ORDER BY ts", (r["id"],))]
                out.append({"task": r["id"], "flow": r["flow"], "text": r["text"], "feedback": fb})
        return out

    def resolve_feedback(self, tids):
        with self._conn() as c:
            for tid in tids:
                c.execute("UPDATE tasks SET learn=0 WHERE id=?", (tid,))
                c.execute("INSERT INTO events VALUES (?,?,?,?)", (tid, time.time(), "skill", "feedback folded into a skill"))

    def claim_next(self, now=None):
        """Oldest task that needs the worker: new -> planning, approved -> executing (atomic).

        The claim also starts the task's wall clock: the budget in flow.yaml is time the worker spends on the task,
        not time the task waits in the queue or for a person to sign off. `now` is the worker's clock, so one clock
        governs the budget end to end.
        """
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            r = c.execute("SELECT id, status FROM tasks WHERE status IN ('new','approved') "
                          "ORDER BY updated LIMIT 1").fetchone()
            if not r:
                c.execute("COMMIT")
                return None
            to = "planning" if r["status"] == "new" else "executing"
            now = time.time() if now is None else now
            c.execute("UPDATE tasks SET status=?, updated=?, run_started=? WHERE id=?", (to, now, now, r["id"]))
            c.execute("COMMIT")
        return self.get(r["id"], events=False)

    def wait(self, tid, timeout=50, poll=1.0):
        """Block until the task needs someone (backbrief ready, finished, failed) or timeout. The callback."""
        start, t = time.time(), self.get(tid)
        while t["status"] not in FINAL + WAITING and time.time() - start < timeout:
            time.sleep(poll)
            t = self.get(tid)
        return t


# ---------- running Hermes ----------

@dataclass
class RunResult:
    text: str
    exit_code: int
    log: str
    session_id: str = ""     # the Hermes session the run used (printed by -Q)


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _clean_output(out):
    """Hermes -Q prints tool previews (boxed, coloured diffs), the answer, then session info; keep the answer."""
    lines = []
    for l in _ANSI.sub("", out).splitlines():
        if re.match(r"^\s*(session[ _]?id|session:|resume with)", l, re.I) or l.lstrip().startswith("│"):
            continue
        lines.append(l)
    return "\n".join(lines).strip()


_SESSION_ID = re.compile(r"session_id:\s*(\S+)")


def hermes_run(flow, phase, prompt, workspace, tid, model=None, session=None):
    """One headless Hermes run in the flow's worker home. session: a Hermes session id to resume (it keeps the model,
    toolsets, skills and turn limit it was started with - Hermes refuses overrides on resume); None starts one."""
    home = flow.home
    # A checkpoint ("checkpoint:plan" / "checkpoint:execute") keeps the toolsets of the phase it closes (same system
    # prompt, so the parked KV cache still matches) but runs read-only, with a few turns.
    side = phase.startswith(("checkpoint", "learn", "review"))   # read-only side runs
    tools_phase = phase.split(":", 1)[1] if ":" in phase else phase
    (home / "ariadne_phase").write_text("plan" if side else phase, encoding="utf-8")
    (home / "ariadne_task").write_text(tid, encoding="utf-8")            # read by the jobs MCP server
    (home / "ariadne_workspace").write_text(str(workspace), encoding="utf-8")
    qfile = paths.LOGS / f"{tid}-{phase.replace(':', '-')}-{int(time.time())}.prompt.md"
    qfile.write_text(prompt, encoding="utf-8")
    # Hermes names an MCP server's toolset "mcp-<server>" (the bare name can collide with a built-in, e.g. memory).
    toolsets = (flow.plan_toolsets if tools_phase == "plan" else flow.execute_toolsets) + [f"mcp-{m}" for m in flow.mcp_servers]
    turns, budget = flow.max_turns.get(phase, 3), flow.run_budget.get(phase, flow.run_budget.get(tools_phase, 900))
    cmd = [str(paths.HERMES_EXE), "chat", "--query-file", str(qfile), "-Q", "--source", "tool"]
    if session:  # a resumed session keeps its launch settings; Hermes rejects any override (budget included)
        cmd += ["--resume", session, "--no-restore-cwd"]
    else:
        cmd += ["--run-budget", str(budget), "--max-turns", str(turns), "-t", ",".join(toolsets)]
        for s in flow.skills + flow.shared_skills:
            cmd += ["-s", s]
        if model:
            cmd += ["-m", model]
        if flow.reasoning.get(tools_phase):  # e.g. low for execute: think less, act more
            cmd += ["--reasoning", flow.reasoning[tools_phase]]
    env = dict(os.environ, HERMES_HOME=str(home), PYTHONIOENCODING="utf-8")
    env.pop("ARIADNE_GUARD_ALL_PROCS", None)
    log = qfile.with_suffix("").with_suffix(".log")
    started = time.time()
    p = subprocess.Popen(cmd, cwd=workspace, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    boundary = park.StepBoundary(home)
    stdout = stderr = ""
    while True:
        try:
            stdout, stderr = p.communicate(timeout=3)  # retrying after a timeout loses no output
            code = p.returncode
            break
        except subprocess.TimeoutExpired:
            pass
        if time.time() > started + budget + 180:
            _kill_tree(p)
            stdout, stderr = p.communicate()
            code = 124
            stop_gateway(home)  # the gateway would keep generating for the killed client
            break
        if park.requested() and not side:
            # Parked on purpose: let the model call / tool call in flight finish, then stop at that boundary.
            if boundary.reached():
                _kill_tree(p)
                stdout, stderr = p.communicate()
                code = PARKED
                break
        else:
            boundary.pos = None
    out = (stdout or "") + ("\n[stderr]\n" + stderr if (stderr or "").strip() else "")
    if code == 124:
        out = "(timed out)\n" + out
    log.write_text(" ".join(cmd) + "\n\n" + out, encoding="utf-8")
    sid = _SESSION_ID.findall(out) or ([session or _latest_session(home, started)] if code == PARKED else [])
    return RunResult(_clean_output(stdout if code != 124 else out), code, str(log), sid[-1] if sid and sid[-1] else "")


PARKED = 125  # exit code of a run stopped by a park request


def _kill_tree(p):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        p.kill()


_TURN_END = re.compile(r"Turn ended: reason=(\S+) .*?session=(\S+)")


def _turn_end_reason(home, session_id):
    """Why Hermes ended the run's last turn (e.g. max_iterations_reached), from its agent.log; '' if unknown."""
    if not session_id:
        return ""
    try:
        with open(Path(home) / "logs" / "agent.log", "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 400_000))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    sid = session_id.strip()
    reasons = [m.group(1) for m in _TURN_END.finditer(tail)
               if len(m.group(2)) >= 12 and (sid.startswith(m.group(2)) or m.group(2).startswith(sid))]
    return reasons[-1].split("(")[0] if reasons else ""


def _latest_session(home, since):
    """The Hermes session a killed run was writing (its id is only printed at a clean exit)."""
    try:
        c = sqlite3.connect(str(home / "state.db"), timeout=10)
        r = c.execute("SELECT id FROM sessions WHERE started_at >= ? ORDER BY started_at DESC LIMIT 1",
                      (since - 2,)).fetchone()
        c.close()
        return r[0] if r else ""
    except sqlite3.Error:
        return ""


# ---------- prompts ----------

PLAN_PROMPT = """You are the {flow} worker of Ariadne, a local agent harness. This is the PLAN phase: you may only read
(files, search, shared memory, git status/diff/log). Nothing is changed until a person approves your plan.

TASK (from {source}):
{text}

WORKSPACE: {workspace}
{feedback}
HOW THIS FLOW WORKS (flows/{flow}/FLOW.md - the coordination this plan must follow; it is the knowledge a small
model cannot invent, so follow it unless the task clearly needs otherwise, and say why if you do not):
{flow_brief}

SHARED SKILLS for this flow (written by the larger models from earlier tasks and the person's feedback; they encode
how this work is actually done here. Read the ones that apply with skill_view before planning, and follow them):
{skills_block}

CHECK GATES agreed with the person (the task is done only when every one passes; plan so that each will):
{gates}

SHARED MEMORY (what earlier tasks recorded):
{memory}

After sign-off the execute phase will have only these tools: {exec_tools}. Plan only steps those tools can do.

MODELS you may assign to steps (one per step; {default_model} if a step does not need anything else):
{models}
Agent models do a step themselves. A generate model drafts text for a step (the agent asks it through
generate_text); an image model renders images (generate_image). Prefer the MoE models: on this machine they read
and write several times faster, so steps finish sooner. You ({planner}) are the planner; assign yourself or another
dense model only to a step that needs the deepest reasoning (hard debugging, tricky design decisions), and say why.
Each step (or run of steps on one model) executes in a fresh session that only gets a summary of earlier steps, so
every step must leave its output in files; never plan a "think only" step whose result a later step on another
model has to write down. Fewer model changes is better: switch models only where it clearly pays.
Work that can run for minutes (ingest, embedding, installs, builds, evals, full test suites) is not run by the model:
the step writes a script and submits it as a job when the execute tools include submit_job (the jobs skill), else it
follows the long-jobs skill. Plan it as: write the script with a sample mode -> job: sample run -> job: full run
(resumable, writes a report file) -> check the report. Each job's result wakes the model to do the next step.

Investigate just enough to plan well (look at the relevant files). Then reply with a backbrief in exactly this form:

MISSION: <one sentence: what will be true when this is done>
FLOW: {flow}
STEPS:
1. <step> - tools: <tools it uses> - model: <model name from MODELS>
2. ...
GATES: <each gate G1..Gn, and which step makes it pass>
RISKS: <what could go wrong, or 'none'>
QUESTIONS: <anything the person must answer first, or 'none'>

After that document, end with one fenced json block and nothing after it. The harness reads the block to build the
sign-off sheet; it must be valid JSON with exactly these keys:

```json
{{"mission": "one line", "steps": [{{"n": 1, "text": "one step"}}],
 "gates": ["which step makes each gate pass"], "risks": ["..."], "questions": ["..."]}}
```

Do not name models in the block: the person chooses the task's model at sign-off.
"""

EXEC_PROMPT = """You are the {flow} worker of Ariadne. This is the EXECUTE phase. The plan below was approved by the person
who gave the task. Carry it out step by step in the workspace. Stay on the plan.

TASK: {text}
WORKSPACE: {workspace}

APPROVED PLAN:
{plan}
{extra}
Rules:
- If a step cannot be done as planned, or the plan turns out to be wrong, stop and reply starting with
  'OFF-PLAN:' and the reason. Do not improvise a different plan.
{jobs_rule}
- At the end, record in shared memory (memory_record) anything a later task should know about this workspace.
- Finish with a short report: what you changed, how you verified it.
"""

JOBS_RULE = """- You write code and scripts; Ariadne runs the heavy work. Installs, ingest, embedding, builds, evals, full test
  suites, downloads: write the script, call submit_job (jobs tools), then end your turn with
  'JOB SUBMITTED: <id>'. You are unloaded while it runs and woken here with the result. Quick commands (read,
  grep, git status, one test file) stay in the terminal. Follow the jobs skill."""
NO_JOBS_RULE = """- Anything that may take more than 2 minutes: follow the long-jobs skill (sample first, then terminal
  background=true with progress in a log, wait with process_manage, resume rather than restart)."""


def jobs_rule(flow):
    return JOBS_RULE if "jobs" in flow.mcp_servers else NO_JOBS_RULE


def skills_block(flow_name: str) -> str:
    """The flow's shared skills, name and description, for the plan prompt.

    These are the skills the larger models wrote from earlier tasks and the person's feedback. Loading them into
    the plan is what makes that writing steer the next run instead of sitting in a folder.
    """
    from . import skills as skilllib
    try:
        rows = skilllib.list_skills(flow_name)
    except Exception:
        return "(none yet)"
    return "\n".join(f"- {r['name']}: {r['description']}" for r in rows) or "(none yet)"


def _install_system_tools(names):
    """Install the system tools the backbrief named. Reached only after the person approved the plan."""
    from . import deps
    deps.install(system=True)


# ---------- model plan: a model per step, suggested by the planner, locked at sign-off ----------

STEP_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
MODEL_RE = re.compile(r"\bmodel:\s*`?([A-Za-z0-9][\w.\-]*)", re.I)
SECTION_RE = re.compile(r"^[A-Z][A-Z ]+:")


def parse_model_plan(plan_text, flow, catalog, default_model=None):
    """The backbrief's steps and the model each names; a missing or unknown name gets the task's explicit model."""
    default = default_model or flow.step_model
    steps, notes, in_steps = [], [], False
    for line in plan_text.splitlines():
        s = line.strip()
        if s.upper().startswith("STEPS"):
            in_steps = True
            continue
        if not in_steps:
            continue
        m = STEP_RE.match(line)
        if not m:
            if SECTION_RE.match(s):
                break
            continue
        body = m.group(2).strip()
        found = MODEL_RE.search(body)
        name = found.group(1).rstrip(".,;") if found else ""
        if name and name not in catalog.models:
            notes.append(f"step {m.group(1)} named '{name}', which is not in the catalog; using {flow.step_model}")
            name = ""
        steps.append({"n": int(m.group(1)), "text": body, "model": name or default})
    return {"steps": steps, "agent": default, "notes": notes}


def apply_model_overrides(mp, overrides):
    """{step or 'all': name} (or 'STEP=NAME,...') -> the model plan with those choices. Raises TaskError."""
    from . import models as modellib
    if isinstance(overrides, str):
        overrides = dict(p.split("=", 1) for p in overrides.replace(" ", "").split(",") if "=" in p)
    cat = modellib.load()
    mp = json.loads(json.dumps(mp))
    for key, name in overrides.items():
        key, name = str(key).strip(), str(name).strip()
        try:
            m = cat.get(name)
        except modellib.ModelError as e:
            raise TaskError(str(e))
        if m.kind not in ("agent", "generate", "image"):
            raise TaskError(f"{name} is a {m.kind} model; a step needs an agent, generate or image model")
        if key == "all":
            targets = mp["steps"]
            if m.kind == "agent":
                mp["agent"] = name
        else:
            targets = [s for s in mp["steps"] if str(s["n"]) == key]
            if not targets:
                raise TaskError(f"the plan has no step {key}")
        for s in targets:
            s["model"] = name
    return mp


def model_summary(mp):
    return ", ".join(f"{s['n']}={s['model']}" for s in mp["steps"]) or f"all={mp['agent']}"


def agent_for(step, mp, catalog):
    """The agent model that runs a step: its own model, or the plan's agent when the step's model is not one."""
    return step["model"] if catalog.get(step["model"]).kind == "agent" else mp["agent"]


def needed_models(mp, catalog):
    names = [s["model"] for s in mp["steps"]] + [agent_for(s, mp, catalog) for s in mp["steps"]]
    return list(dict.fromkeys(names or [mp["agent"]]))


def needed_servers(mp, catalog):
    """MCP servers the chosen models are reached through (image -> image, generate -> text)."""
    kinds = {catalog.get(s["model"]).kind for s in mp["steps"]}
    return [srv for kind, srv in (("image", "image"), ("generate", "text")) if kind in kinds]


def step_groups(mp, catalog):
    """Consecutive steps run by the same agent model share one Hermes run: [(agent, [steps])]."""
    groups = []
    for s in mp["steps"]:
        a = agent_for(s, mp, catalog)
        if groups and groups[-1][0] == a:
            groups[-1][1].append(s)
        else:
            groups.append((a, [s]))
    return groups or [(mp["agent"], [])]


def model_block(mp, flow, catalog):
    """What the harness adds to the backbrief: the model per step, what will be fetched, what tools are missing."""
    out = ["", "MODEL PLAN (sign-off locks these; anything not installed is fetched before step 1):"]
    out.append(f"  task model: {mp.get('agent')}")
    for s in mp["steps"] or [{"n": "all", "model": mp["agent"]}]:
        m = catalog.get(s["model"])
        state = "installed" if m.installed() else f"not installed, {m.size_gb:g} GB"
        via = "" if m.kind == "agent" else f", run by {agent_for(s, mp, catalog) if mp['steps'] else mp['agent']}"
        out.append(f"  step {s['n']}: {m.name} ({m.kind}, {state}{via})")
    out += [f"  note: {n}" for n in mp["notes"]]
    todo = [n for n in needed_models(mp, catalog) if not catalog.get(n).installed()]
    if todo:
        out.append("TO FETCH AFTER SIGN-OFF: " + ", ".join(f"{n} ({catalog.get(n).size_gb:g} GB)" for n in todo))
    gaps = missing_tools(mp, flow, catalog)
    need = missing_system(flow)
    if need:
        # Named here, in the plan, because approving the brief is what authorises the download.
        out.append("TO INSTALL AFTER SIGN-OFF: " + "; ".join(f"{m} ({flowlib.install_hint(m)})" for m in need))
    bad = missing_servers(mp, flow, catalog)
    if bad:
        out.append("PLAN ERROR - the flow does not enable MCP server(s): " + ", ".join(bad)
                   + f" (add them to flows/{flow.name}/flow.yaml)")
    if gaps and not need:
        out.append("MISSING TOOLS (execution will not start until they are there): " + "; ".join(gaps))
    out.append("Change a model: approve with --model STEP=NAME (or all=NAME), or revise. Models: python -m ariadne models")
    return "\n".join(out)


def missing_system(flow):
    """System tools the flow declares and this machine lacks (installable, named in the backbrief)."""
    return flowlib.missing_requirements(flow)


def missing_servers(mp, flow, catalog):
    """MCP servers the chosen models need but the flow does not enable - a planning error, not a download."""
    return [s for s in needed_servers(mp, catalog) if s not in flow.mcp_servers]


def missing_tools(mp, flow, catalog):
    gaps = [f"{m} ({flowlib.install_hint(m)})" for m in missing_system(flow)]
    gaps += [f"MCP server '{s}' (add it to mcp_servers in flows/{flow.name}/flow.yaml)"
             for s in missing_servers(mp, flow, catalog)]
    return gaps


def step_scope(steps, groups, mp, catalog):
    """What an execute run is told to do now: its steps (when the plan is split) and how to use other models."""
    lines = []
    if len(groups) > 1:
        lines.append(f"NOW DO STEP{'S' if len(steps) > 1 else ''} {', '.join(str(s['n']) for s in steps)} ONLY. "
                     "Earlier steps are done; later steps run separately.")
    for s in steps:
        m = catalog.get(s["model"])
        if m.kind == "generate":
            lines.append(f"Step {s['n']}: have {m.name} write the text: generate_text(model='{m.name}', prompt=...).")
        elif m.kind == "image":
            lines.append(f"Step {s['n']}: render with generate_image(model='{m.name}', ...).")
    return ("\n" + "\n".join(lines) + "\n") if lines else ""


CHECKPOINT_PROMPT = """CHECKPOINT: {reason}. Pause here and do not call any tools.
This conversation is about to be replaced by what you write now. Write the handoff brief the next worker needs to
carry on without it:

SITUATION: what this session is working on, in which workspace, for which task
DONE: what has been done (files changed, commands run, results), with exact paths and names
STATE: decisions made, facts learned, what is verified and what is not
OPEN: what is left to do, problems, failing checks
{extra}
Facts only, complete but brief (under 600 words)."""

REVIEW_PROMPT = """QA REVIEW. You are checking finished work against the gates the person set. Inspect the workspace
({workspace}) with your read tools; do not change anything. Be strict: a gate passes only if you saw the evidence.

TASK: {text}

GATES TO REVIEW:
{gates}

Reply with one line per gate, exactly:
G<n>: PASS - <evidence>    or    G<n>: FAIL - <what is missing or wrong>"""

JOB_RESULT_PROMPT = """You were asleep while Ariadne ran the job(s) you submitted, with the machine to itself. Results:

{results}

Read them and continue the approved plan from here: fix and resubmit if a job failed (resume, do not start over),
otherwise go on to the next step. Heavy work again goes through submit_job."""

RESUME_PROMPT = """You were paused at a step boundary so the person could use the model. Continue the same task where
you left off. If your last tool call has no result, run it again; re-read a file before editing it."""

HANDOFF = """SESSION HANDOFF - the earlier work in this session, compressed at a checkpoint. Trust it; re-read files
only where you need detail.
{summary}

---

"""

ROUTE_PROMPT = """Pick the flow for this task. Flows:
{flows}

Task: {text}

Reply with only the flow name."""


# ---------- the worker ----------

class Worker:
    def __init__(self, store=None, memory=None, flows=None, runner=hermes_run, router_model="router", llm_chat=None,
                 catalog=None, installer=None, on_installed=None, kv=None, job_runner=None, unload=None,
                 install_tools=None, clock=None):
        from . import kvcache
        # Jobs run for real only with the real runner; tests pass a fake that never unloads the model server.
        self.job_runner = job_runner or (jobs.run if runner is hermes_run else
                                         (lambda j, db: jobs.run(j, db, unload=lambda: True, poll=0.05)))
        # Same rule for freeing VRAM: only the real runner has a model server behind it.
        self.unload = unload or (jobs.unload_models if runner is hermes_run else (lambda: True))
        self.kv = kv or (kvcache.default() if runner is hermes_run else kvcache.NoKVCache())
        from . import models as modellib
        self.catalog = catalog or modellib.load()
        self.installer = installer or modellib.install
        self.install_tools = install_tools or _install_system_tools
        self.on_installed = on_installed or _reload_models
        self.store = store or Store()
        self.memory = memory or Memory()
        self.flows = flows or flowlib.load_flows()
        self.runner = runner
        self.router_model = router_model
        self.llm_chat = llm_chat or llm.chat
        self.now = clock or time.time   # the task wall clock reads through this, so a test can spend time

    def route(self, t):
        """The flow, or None with the reason: a task outside the approved set is rejected, never guessed at."""
        if t["flow"]:
            if t["flow"] in self.flows:
                return t["flow"], "given by the task"
            return None, f"'{t['flow']}' is not an approved flow"
        if len(self.flows) == 1:
            return next(iter(self.flows)), "only flow"
        listing = "\n".join(f"- {f.name}: {f.when}" for f in self.flows.values())
        try:
            answer = self.llm_chat(self.router_model, [{"role": "user", "content": ROUTE_PROMPT.format(
                flows=listing, text=t["text"])}]).lower()
        except Exception as e:  # router down: say so, do not invent a flow
            self.store.event(t["id"], "route", f"router failed ({e})")
            return None, f"the router could not run ({e})"
        for name in self.flows:
            if re.search(rf"\b{re.escape(name)}\b", answer):
                return name, f"router said '{answer[:60]}'"
        return None, f"the router named no approved flow (it said {answer[:60]!r})"

    def workspace(self, t):
        ws = t["workspace"] or str(paths.STATE / "workspace")
        Path(ws).mkdir(parents=True, exist_ok=True)
        return ws

    def plan(self, t):
        name, why = self.route(t)
        if not name:
            approved = ", ".join(self.flows)
            self.store.update(t["id"], status="rejected",
                              result=(f"No approved flow: {why}.\n"
                                      f"Approved flows: {approved}.\n"
                                      "Give the task again with --flow <name>, or reword it so the router can pick "
                                      "one of them."))
            self.store.event(t["id"], "route", f"rejected: {why}")
            return
        flow = self.flows[name]
        missing = flowlib.missing_requirements(flow)
        if missing:
            msg = (f"flow '{name}' needs {', '.join(missing)}, which this machine does not have. "
                   "Install them (python -m ariadne install --system), then revise the task to retry.")
            self.store.update(t["id"], flow=name, status="needs_attention", result=msg)
            self.store.event(t["id"], "route", f"{name}: missing {', '.join(missing)}")
            return
        self.store.update(t["id"], flow=name)
        self.store.event(t["id"], "route", f"{name} ({why})")
        planner = self.catalog.get((t.get("model") or "").strip() or flow.model)
        if not planner.installed():
            msg = (f"flow '{name}' plans and works with {planner.name}, which is not installed "
                   f"({planner.size_gb:g} GB). Install it (python -m ariadne models install {planner.name}), "
                   f"then revise the task to retry.")
            self.store.update(t["id"], status="needs_attention", result=msg)
            self.store.event(t["id"], "route", f"{flow.model} not installed")
            return
        ws = self.workspace(t)
        hits = self.memory.recall(f"{t['text']} {ws}", limit=5)
        feedback = f"\nFEEDBACK ON THE LAST PLAN (address it):\n{t['feedback']}\n" if t["feedback"] else ""
        default_model = (t.get("model") or "").strip() or flow.step_model
        prompt = PLAN_PROMPT.format(flow=name, source=t["source"], text=t["text"], workspace=ws,
                                    gates=gates_text(json.loads(t.get("gates") or "[]")) or "(none)",
                                    feedback=feedback, memory=format_hits(hits),
                                    flow_brief=flow.brief or "(this flow has no FLOW.md)",
                                    skills_block=skills_block(name),
                                    exec_tools=", ".join(flow.execute_toolsets + [f"{m} (MCP)" for m in flow.mcp_servers]),
                                    models=self.catalog.text(), default_model=default_model, planner=planner.name)
        self.store.event(t["id"], "plan", f"started ({len(hits)} memories recalled)")
        r = self.run(flow, "plan", prompt, ws, t, planner.name, "plan")
        if r.exit_code != 0 or not r.text:
            self.store.update(t["id"], status="failed", error=f"plan run failed (exit {r.exit_code}); log {r.log}")
            self.store.event(t["id"], "plan", f"failed, log {r.log}")
            return
        try:
            plan = protocol.parse(r.text, default_model)
            mp = {"steps": plan["steps"], "agent": default_model, "notes": []}
            document = render.backbrief(plan)
            self.store.update(t["id"], plan_json=protocol.to_json(plan))
        except protocol.PlanError as e:
            # One release of tolerance: an older planner that answers in prose still reaches sign-off, and the
            # backbrief says the structure was read from the text.
            mp = parse_model_plan(r.text, flow, self.catalog, default_model=default_model)
            mp["notes"].append(f"the reply had no usable JSON plan ({e}); read from the text instead")
            document = r.text
        self.store.update(t["id"], status="awaiting_signoff",
                          plan=document.rstrip() + "\n" + model_block(mp, flow, self.catalog),
                          models=json.dumps(mp))
        self.store.event(t["id"], "backbrief", "ready for sign-off")
        self.memory.record("task", t["id"], f"{t['text']}\nstatus: awaiting sign-off",
                           [("uses_flow", "flow", name), ("in_workspace", "workspace", ws)])

    def segment(self, t, flow):
        """The session row and the Hermes session (segment) the next run continues: <name>~<n>. Moving to another
        flow starts a new segment (its own Hermes home) seeded with the last handoff brief."""
        s = self.store.session(t.get("session") or t["id"], t.get("source", ""))
        if s["flow"] != flow.name:
            seg = s["segment"] + 1 if s["flow"] else s["segment"]
            self.store.session_update(s["name"], flow=flow.name, segment=seg, fresh=1 if s["summary"] else 0,
                                      hermes_id="")
            s = self.store.session(s["name"])
        return s, f"{s['name']}~{s['segment']}"

    def run(self, flow, phase, prompt, ws, t, model, scope):
        """One Hermes run in the task's session segment on `model`. A fresh segment's first run is seeded with the
        handoff brief. The KV cache for (segment, step, model) is woken first and parked after (kvcache.py)."""
        s, title = self.segment(t, flow)
        seeded = bool(s["fresh"] and s["summary"])
        if seeded:
            prompt = HANDOFF.format(summary=s["summary"]) + prompt
        # Within a segment the Hermes session is resumed (same model and tools by construction: a segment is one
        # phase on one model); a new segment starts a new Hermes session.
        # The stored id is "<phase>/<model>|<hermes id>": resume only a session started for the same phase and model.
        sig = f"{phase.split(':')[-1]}/{model}"
        stored_sig, _, stored_id = (s["hermes_id"] or "").partition("|")
        resume = stored_id if stored_id and stored_sig == sig else None
        side = phase.startswith(("checkpoint", "learn", "review"))
        if park.requested() and not side:  # parked by the person: hold before starting anything new
            self._hold(t, model)
        # Wake a parked cache only when resuming: a new Hermes session has a new prefix, nothing would match.
        note = self.kv.restore(title, model, scope) if resume else ""
        if note:
            self.store.event(t["id"], "kv", f"{model}: {note}")
        r = self.runner(flow, phase, prompt, ws, t["id"], model=model, session=resume)
        # Park only what a later run resumes (plan and execute sessions); side runs are not resumed.
        note = self.kv.save(title, model, scope) if not side else ""
        if note:
            self.store.event(t["id"], "kv", f"{model}: {note}")
        while r.exit_code == PARKED:  # stopped at a step boundary on request: wait, then continue the same session
            self.store.event(t["id"], "park", f"stopped at a step boundary on {model}; the model is free")
            self._hold(t, model)
            note = self.kv.restore(title, model, scope) if r.session_id else ""
            if note:
                self.store.event(t["id"], "kv", f"{model}: {note}")
            again = RESUME_PROMPT if r.session_id else prompt
            r = self.runner(flow, phase, again, ws, t["id"], model=model, session=r.session_id or resume)
            note = self.kv.save(title, model, scope)
            if note:
                self.store.event(t["id"], "kv", f"{model}: {note}")
        if not side:
            r = self._run_jobs(flow, phase, ws, t, model, scope, title, r, resume)
        if r.exit_code == 0:
            if phase.startswith(("learn", "review")):  # side trips: the segment stays as it was
                return r
            dirty = 0 if phase.startswith("checkpoint") else 1
            self.store.session_update(s["name"], fresh=0, dirty=dirty,
                                      hermes_id=f"{sig}|{r.session_id}" if r.session_id else s["hermes_id"])
        return r

    MAX_JOB_CYCLES = 40

    def _run_jobs(self, flow, phase, ws, t, model, scope, title, r, resume):
        """The callback loop: while the model has submitted jobs, run them with the model unloaded (its KV cache is
        already parked), then wake the same Hermes session with the results. Ends when a run submits no job."""
        cycles = 0
        while cycles < self.MAX_JOB_CYCLES:
            pending = jobs.for_task(t["id"], "pending", self.store.db_path)
            if not pending:
                return r
            cycles += 1
            results = []
            for j in pending:
                self.store.event(t["id"], "job", f"{j['id']} started: {j['why'] or j['command']} (model unloaded)")
                j = self.job_runner(j, self.store.db_path)
                res = json.loads(j.get("result") or "{}")
                self.store.event(t["id"], "job", f"{j['id']} {j['status']}: exit {j['exit_code']} in "
                                                 f"{res.get('seconds')} s")
                results.append(jobs.result_text(j))
            session = r.session_id or resume
            note = self.kv.restore(title, model, scope) if session else ""
            if note:
                self.store.event(t["id"], "kv", f"{model}: {note}")
            prompt = JOB_RESULT_PROMPT.format(results="\n\n".join(results))
            r = self.runner(flow, phase, prompt, ws, t["id"], model=model, session=session)
            note = self.kv.save(title, model, scope)
            if note:
                self.store.event(t["id"], "kv", f"{model}: {note}")
        self.store.event(t["id"], "job", f"stopped after {self.MAX_JOB_CYCLES} job cycles")
        return r

    def _hold(self, t, model):
        """Parked: give the model to the person until they resume (never resumes on its own)."""
        by = (park.requested() or {}).get("by", "")
        park.mark_parked(t["id"], model)
        self.store.event(t["id"], "park", by if by.startswith("login needed") else
                         "parked: waiting for resume (desktop button or `python -m ariadne park --resume`)")
        park.wait_resumed()
        self.store.event(t["id"], "park", "resumed")
        flow = self.flows.get(t.get("flow") or "")
        if flow:   # debug mode may have changed while parked: the resumed run's browser follows it
            try:
                flowlib.compile_flow(flow)
            except Exception as e:
                self.store.event(t["id"], "park", f"could not refresh the flow's tools: {e}")

    def checkpoint(self, t, flow, ws, model, reason, closes="execute", extra=""):
        """Pause and compress at a phase boundary: the model that just worked (still loaded, cache hot) writes a
        handoff brief; the next run starts a new segment seeded with it. Skipped when nothing ran since the last
        checkpoint. A failed checkpoint just leaves the session uncompressed."""
        s, title = self.segment(t, flow)
        if not s["dirty"]:
            return
        r = self.run(flow, f"checkpoint:{closes}", CHECKPOINT_PROMPT.format(reason=reason, extra=extra), ws, t,
                     model, "checkpoint")
        if r.exit_code != 0 or not r.text.strip():
            self.store.event(t["id"], "compress", f"{reason}: skipped (exit {r.exit_code}); continuing uncompressed")
            return
        self.store.session_update(s["name"], segment=s["segment"] + 1, summary=r.text.strip()[:12000], fresh=1, dirty=0,
                                  hermes_id="")
        self.kv.drop(title)
        self.store.event(t["id"], "compress", f"{reason}: {title} -> {s['name']}~{s['segment'] + 1} "
                                              f"(handoff {len(r.text)} chars)")

    def qa(self, t, flow, ws, model):
        """QA after execution: the flow's checks, the task's command gates, then a reviewer run for the review gates.
        Returns failure descriptions ([] = every gate passed)."""
        gates = json.loads(t.get("gates") or "[]")
        failures = self.run_checks(flow, ws, [g["text"] for g in gates if g["type"] == "run"])
        review = [(i, g) for i, g in enumerate(gates, 1) if g["type"] == "review"]
        if review:
            r = self.run(flow, "review:plan", REVIEW_PROMPT.format(
                workspace=ws, text=t["text"], gates="\n".join(f"G{i}. {g['text']}" for i, g in review)),
                ws, t, model, "review")
            verdicts = dict(re.findall(r"G(\d+)\s*:\s*(PASS|FAIL)\b", r.text, re.I))
            for i, g in review:
                v = verdicts.get(str(i), "").upper()
                if v != "PASS":
                    line = next((l for l in r.text.splitlines() if re.match(rf"\s*G{i}\s*:", l)), "no verdict")
                    failures.append(f"G{i} [review] {g['text']}: {line.strip()[:500]}")
            self.store.event(t["id"], "qa", f"review: {sum(1 for i, _ in review if verdicts.get(str(i), '').upper() == 'PASS')}"
                                            f"/{len(review)} gates passed")
        return failures

    def run_checks(self, flow, ws, extra_cmds=()):
        failures = []
        for check in list(flow.checks) + list(extra_cmds):
            # A check is a shell command, or {run: cmd, when_exists: path} to run only if that path exists.
            cmd, cond = (check.get("run"), check.get("when_exists")) if isinstance(check, dict) else (check, None)
            if not cmd or (cond and not (Path(ws) / cond).exists()):
                continue
            cmd = flowlib._expand(cmd)  # {python} = Ariadne's Python, which has pytest
            p = subprocess.run(cmd, shell=True, cwd=ws, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=600)
            if p.returncode != 0:
                failures.append(f"$ {cmd}\n(exit {p.returncode})\n{(p.stdout + p.stderr)[-3000:]}")
        return failures

    def prepare(self, t, flow, mp):
        """Before step 1: every tool the plan needs is there and every locked model is installed.

        The backbrief named anything missing, so approving it authorised the download: models are fetched and
        system tools installed. Only a configuration error still stops the task.
        """
        bad = [f"MCP server '{s}' (add it to mcp_servers in flows/{flow.name}/flow.yaml)"
               for s in missing_servers(mp, flow, self.catalog)]
        too_big = [n for n in needed_models(mp, self.catalog) if not self.catalog.fits(self.catalog.get(n))
                   and self.catalog.get(n).kind != "image"]
        if too_big:
            b = self.catalog.active_budget()
            bad.append(f"{', '.join(too_big)} too large for the '{b['profile']}' resource profile "
                       f"(max {b['max_model_gb']} GB; python -m ariadne resources shared)")
        if bad:
            return "Execution did not start; missing: " + "; ".join(bad) + ". Fix that, then approve again."
        need = missing_system(flow)
        if need:
            self.store.event(t["id"], "install", "installing after sign-off: " + ", ".join(need))
            try:
                self.install_tools(need)
            except Exception as e:
                return (f"Execution did not start: could not install {', '.join(need)}: {e}. Install it "
                        f"(python -m ariadne install --system), then approve again.")
            still = missing_system(flow)
            if still:
                return (f"Execution did not start; still missing {', '.join(still)}. Install it, then approve "
                        "again.")
        from . import models as modellib
        fetch = modellib.missing(needed_models(mp, self.catalog), self.catalog)
        for name in fetch:
            self.store.event(t["id"], "install", f"{name} ({self.catalog.get(name).size_gb:g} GB)")
            try:
                self.installer(name, self.catalog, log=lambda s: self.store.event(t["id"], "install", s))
            except Exception as e:
                return (f"Execution did not start: could not install {name}: {e}. Install it "
                        f"(python -m ariadne models install {name}) or approve with --model to pick another.")
        if fetch:
            self.on_installed()
        return ""

    def _sleep(self, t, why):
        """Give the machine back: unload the orchestrator model until a new plan is needed.

        The planner is the largest model in the flow and is not used again until re-planning (revise, off-plan).
        Holding it while the executor works is what made one GPU thrash: the worker's own model should be the only
        thing on the card while a task runs.
        """
        try:
            freed = self.unload()
        except Exception as e:
            self.store.event(t["id"], "vram", f"could not unload the orchestrator model: {e}")
            return
        if freed:
            self.store.event(t["id"], "vram", f"orchestrator model unloaded ({why}); it waits for the task")

    def execute(self, t):
        flow = self.flows.get(t["flow"])
        if not flow:
            self.store.update(t["id"], status="failed", error=f"flow '{t['flow']}' no longer exists")
            return
        mp = json.loads(t["models"]) if t.get("models") else {"steps": [], "agent": flow.step_model, "notes": []}
        problem = self.prepare(t, flow, mp)
        if problem:
            self.store.update(t["id"], status="needs_attention", result=problem)
            self.store.event(t["id"], "prepare", problem[:300])
            return
        ws = self.workspace(t)
        self.checkpoint(t, flow, ws, flow.model, "plan approved", closes="plan",
                        extra="Include the approved plan's steps verbatim under OPEN.")
        # The brief is delivered and signed off; the planner is not needed again until a re-plan.
        self._sleep(t, "the plan is signed off")
        groups, reports = step_groups(mp, self.catalog), []
        budget = int(getattr(flow, "task_budget", 0) or 0)
        if budget:
            self.store.event(t["id"], "budget", f"task wall clock: {budget} s of worker time from now")
        for i, (agent, steps) in enumerate(groups):
            scope, extra, attempts, last = step_scope(steps, groups, mp, self.catalog), "", 0, i == len(groups) - 1
            history = []  # failing-gate counts per QA round (loop end: no progress)
            label = f"steps {', '.join(str(s['n']) for s in steps)}" if len(groups) > 1 else "plan"
            while True:
                if self._expired(t, flow):
                    # Out of wall-clock is not out of options: stop running, keep what was written, let the gates
                    # that need no model decide (docs/COVERAGE.md, the runtime contract).
                    return self._out_of_time(t, flow, ws, reports, label)
                attempts += 1
                self.store.event(t["id"], "execute", f"{label} on {agent}, attempt {attempts}")
                r = self.run(flow, "execute", EXEC_PROMPT.format(flow=flow.name, text=t["text"], workspace=ws,
                                                                  jobs_rule=jobs_rule(flow),
                                                                  plan=t["plan"], extra=scope + extra), ws, t, agent,
                             "step-" + "-".join(str(s["n"]) for s in steps) if steps else "steps-all")
                out_of = "time" if r.exit_code == 124 else (
                    "turns" if r.exit_code != 0 and _turn_end_reason(flow.home, r.session_id) == "max_iterations_reached"
                    else "")
                if out_of:
                    # Out of time or turns is not out of options: what it wrote stays and the gates decide. This is
                    # true for every step group, not only the last one - an unfinished group is unfinished, and the
                    # next group (or QA) continues from the files it left behind.
                    what = "run budget" if out_of == "time" else "turn limit"
                    self.store.event(t["id"], "execute", f"{what} used up on {label} (attempt {attempts}); "
                                                         "keeping what it wrote")
                    r = RunResult(r.text.strip() or (f"STOPPED ({what} used up) before finishing; continue from the "
                                                     "files as they are."), 0, r.log, r.session_id)
                elif r.exit_code != 0 or not r.text:
                    return self._finish(t, flow, ws, "failed", "\n\n".join(reports + [r.text]),
                                        f"execute run failed (exit {r.exit_code}); log {r.log}")
                if r.text.lstrip().upper().startswith("OFF-PLAN"):
                    # The plan was wrong, not the work: `error` marks why, so approving sends the task back to
                    # planning (a new backbrief) instead of re-running the plan that just failed.
                    self.store.update(t["id"], status="needs_attention", result=r.text, error="off-plan")
                    self.store.event(t["id"], "execute", "stopped: off-plan, back to the person for a new sign-off")
                    self.checkpoint(t, flow, ws, agent, "stopped off-plan", extra="Say why under OPEN.")
                    return
                if not last:
                    reports.append(r.text)
                    self.checkpoint(t, flow, ws, agent, f"{label} done")
                    break
                if self._expired(t, flow):
                    # The work is in; there is no time left to run the reviewer, so end on the gates a script can run.
                    return self._out_of_time(t, flow, ws, reports + [r.text], label)
                failures = self.qa(t, flow, ws, agent)
                qa = "QA passed: every gate" if not failures else f"QA failed ({len(failures)} gate(s)), iteration {attempts}"
                self.checkpoint(t, flow, ws, agent, qa,
                                extra=("QA RESULTS (put them under OPEN):\n" + "\n".join(failures)) if failures else "")
                if not failures:
                    has_cmds = flow.checks or any(g["type"] == "run" for g in json.loads(t.get("gates") or "[]"))
                    self.store.event(t["id"], "checks", "passed (every gate)" if has_cmds else
                                     "passed (review gates only; no command gates)")
                    self._finish(t, flow, ws, "done", "\n\n".join(reports + [r.text]))
                    return
                self.store.event(t["id"], "checks", f"failed: {failures[0][:300]}")
                # Loop end: the gates pass, max_iterations is reached, or two iterations in a row fail as many
                # gates as before (no progress: more of the same will not get there).
                history.append(len(failures))
                stalled = len(history) >= 3 and history[-1] >= history[-2] >= history[-3]
                if attempts >= flow.max_iterations or stalled:
                    why = "no progress in the last two iterations" if stalled else f"{attempts} iterations"
                    return self._finish(t, flow, ws, "failed", "\n\n".join(reports + [r.text]),
                                        f"gates still failing after {why}:\n" + "\n".join(failures))
                self.store.event(t["id"], "iterate", f"{len(failures)} gate(s) failing; iteration {attempts + 1} "
                                                     f"of at most {flow.max_iterations}")
                extra = ("\nA PREVIOUS ATTEMPT FINISHED BUT THESE GATES FAILED. The cause may be in any step of the "
                         "plan above, not only the last one that ran: read the plan, find the step that owns each "
                         "failure, and fix it without redoing steps that are already proven.\n"
                         + "\n".join(failures) + "\n")

    def _expired(self, t, flow):
        """Is the task's wall clock spent? `task_budget` seconds of worker time, from flow.yaml (0 = no limit).

        Time waiting in the queue or for a sign-off does not count: `claim_next` restarts the clock every time the
        worker picks the task up, so a brief that sits overnight is not timed out the moment it is approved.
        """
        budget = int(getattr(flow, "task_budget", 0) or 0)
        started = float(t.get("run_started") or 0)
        return bool(budget and started and self.now() - started >= budget)

    def _out_of_time(self, t, flow, ws, reports, label=""):
        """The wall clock is spent between phases: stop running the model and let the gates that need no model decide.

        What was written stays in the workspace. Command gates run; a review gate needs a reviewer run, which is
        exactly the work there is no time left for, so it is named as not reviewed. All commands pass and nothing
        needs a reviewer -> the task is `done`; otherwise it ends `timed_out` with the gate results and the reason.
        """
        budget = int(getattr(flow, "task_budget", 0) or 0)
        self.store.event(t["id"], "timeout",
                         f"wall clock spent ({budget} s) during {label or 'the run'}; keeping what was written and "
                         "running the gates a script can run")
        gates = json.loads(t.get("gates") or "[]")
        failures = self.run_checks(flow, ws, [g["text"] for g in gates if g["type"] == "run"])
        unreviewed = [f"G{i} [review] {g['text']}" for i, g in enumerate(gates, 1) if g["type"] == "review"]
        body = "\n\n".join(r for r in reports if r)
        if not failures and not unreviewed:
            self.store.event(t["id"], "checks", "passed (command gates, after the wall clock ran out)")
            self._finish(t, flow, ws, "done", (body + "\n\n" if body else "")
                         + f"Ran out of its {budget} s wall clock; every command gate passed, so it is done.")
            return
        detail = []
        if failures:
            detail.append("FAILING GATES:\n" + "\n".join(failures))
        if unreviewed:
            detail.append("NOT REVIEWED (no time left to run the reviewer):\n" + "\n".join(unreviewed))
        self.store.event(t["id"], "checks", f"out of time; {len(failures)} gate(s) failing, "
                                            f"{len(unreviewed)} not reviewed")
        self._finish(t, flow, ws, "timed_out", "\n\n".join(x for x in [body, *detail] if x),
                     f"the task used its {budget} s wall clock; the work so far is in the workspace")

    def _finish(self, t, flow, ws, status, result, error=""):
        self.store.update(t["id"], status=status, result=result or "", error=error)
        if (t.get("session") or t["id"]) == t["id"]:  # the task's own session ends with it; a caller's lives on
            self.kv.drop(self.segment(t, flow)[1])
        self.store.event(t["id"], "report", status + (f": {error[:300]}" if error else ""))
        self._sleep(t, "the task is finished")
        self.memory.record("task", t["id"], f"{t['text']}\nstatus: {status}\nresult: {(result or error)[:1500]}",
                           [("uses_flow", "flow", flow.name), ("in_workspace", "workspace", ws)])

    def run_once(self):
        t = self.store.claim_next(now=self.now())
        if not t:
            return False
        try:
            if t["status"] == "planning":
                self.plan(t)
            else:
                self.execute(t)
        except Exception as e:  # never leave a task stuck in planning/executing
            self.store.update(t["id"], status="failed", error=f"{type(e).__name__}: {e}")
            self.store.event(t["id"], "error", f"{type(e).__name__}: {e}")
        return True


def _reload_models():
    """Rewrite llama-swap's config so models fetched just now are served (it watches the file)."""
    try:
        from . import serve
        serve.render_config()
    except (Exception, SystemExit) as e:  # models not set up: the run will fail and say so
        print(f"could not refresh the model server config: {e}", flush=True)


# ---------- single worker process ----------

LOCK = paths.STATE / "worker.lock"


def _try_lock(path):
    """Exclusive, non-blocking lock held for the process lifetime. Returns the open file or None."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def _release(f):
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()
    except OSError:
        pass


def worker_running():
    # Resolved at call time: an ARIADNE_STATE (or a test's tmp dir) set after import must still be honoured.
    f = _try_lock(paths.STATE / "worker.lock")
    if f is None:
        return True
    _release(f)
    return False


def ensure_worker():
    from .activity import maybe_open_window
    maybe_open_window()
    return _ensure_worker()


def _ensure_worker():
    """Start the worker process if none is running (detached; its own log; no pipes to the caller)."""
    if os.environ.get("ARIADNE_NO_AUTOSTART") or worker_running():
        return False
    paths.ensure()
    # Outside the caller's session (procs.py): closing the terminal, chat or remote session must not kill it.
    from .procs import spawn_detached
    spawn_detached([paths.PYTHON, "-m", "ariadne.orchestrator", "serve"], paths.LOGS / "worker.log", paths.ROOT,
                   {"PYTHONPATH": str(paths.ROOT), "PYTHONIOENCODING": "utf-8"})
    return True


WORKER_PID = paths.STATE / "worker.pid"


def stop_all(reason="stopped by you"):
    """Stop Ariadne's background work on purpose: the worker, the Hermes gateways it started, and the model server.
    A task that was running goes back to the person (needs_attention) with its work kept in the workspace."""
    from . import park, procs
    from . import serve as model_server
    try:
        pid = json.loads(WORKER_PID.read_text())["pid"]
    except (OSError, ValueError, KeyError):
        pid = 0
    procs.kill_tree(pid)  # the worker and the Hermes run it was waiting on
    WORKER_PID.unlink(missing_ok=True)
    for home in paths.HOMES.glob("*") if paths.HOMES.exists() else []:
        try:
            stop_gateway(home)
        except Exception:
            pass
    model_server.stop()
    park.resume()
    st = Store()
    stopped = []
    for t in st.list(50):
        if t["status"] in ("planning", "executing"):
            st.update(t["id"], status="needs_attention", result=f"{reason}; the work so far is in the workspace. "
                                                               "Approve to continue it.")
            st.event(t["id"], "stop", reason)
            stopped.append(t["id"])
        for j in jobs.for_task(t["id"], db_path=st.db_path):   # a job killed with the worker does not run again
            if j["status"] in ("pending", "running"):
                jobs._update(j["id"], st.db_path, status="cancelled")
    return stopped


def ensure_llm(wait=120):
    if llm.is_up():
        return True
    from . import serve as model_server
    print("models are down; starting them", flush=True)
    try:
        model_server.start()
    except SystemExit as e:
        print(f"could not start the models: {e}", flush=True)
    start = time.time()
    while time.time() - start < wait:
        if llm.is_up():
            return True
        time.sleep(2)
    return False


def stop_gateway(home):
    """Stop the Hermes gateway serving a worker home, if one is running (Hermes's own `gateway stop`)."""
    if not (Path(home) / "gateway.pid").exists():
        return
    # --yes: also interrupt live sessions (an orphaned request would keep a model busy, or reload one later)
    subprocess.run([str(paths.HERMES_EXE), "gateway", "stop", "--yes"], env=dict(os.environ, HERMES_HOME=str(home)),
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=120)


def _code_stamp():
    """Newest change to the worker's code or configuration (Ariadne's modules, flows, skills, model catalog)."""
    files = list((paths.ROOT / "ariadne").glob("*.py")) + list(paths.FLOWS_DIR.rglob("*.yaml")) \
        + list(paths.FLOWS_DIR.rglob("SKILL.md")) + [paths.ROOT / "serving" / "models.yaml"]
    return max((f.stat().st_mtime for f in files if f.exists()), default=0)


def _reconcile(store):
    """A worker that starts finds whatever a previous worker left mid-run (crash, kill, reboot) and hands it back.

    Nothing else can do this: the worker holds the single-process lock, so any row still in planning/executing at
    this point has no worker behind it. Silence here is what leaves a task reading `executing` for two days.
    """
    for t in store.list(50):
        if t["status"] in ("planning", "executing"):
            store.update(t["id"], status="needs_attention",
                         result="The worker restarted while this task was running. The work so far is in the "
                                "workspace. Approve to continue it, or revise it.")
            store.event(t["id"], "recover", "no worker behind it (crash, kill or reboot); back to the person")


def serve(idle_exit=1800):
    from .deps import require
    require()
    lock = _try_lock(LOCK)
    if lock is None:
        print("another Ariadne worker is running", flush=True)
        return 2
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} worker up (pid {os.getpid()})", flush=True)
    WORKER_PID.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}))
    try:
        from .resources import detect_at_boot
        detect_at_boot(log=lambda s: print(s, flush=True))  # GPU/RAM limits for this machine, logged at every start
    except Exception as e:
        print(f"limits: could not measure this machine ({e})", flush=True)
    for name, home in flowlib.compile_all().items():
        print(f"  flow {name} -> {home}", flush=True)
        stop_gateway(home)  # a gateway left from an earlier worker still has the old config; the next run restarts it
    w, last, stamp, restart = Worker(), time.time(), _code_stamp(), False
    _reconcile(w.store)
    try:
        while True:
            if _code_stamp() > stamp:  # updated code or config: hand over to a fresh worker between tasks
                restart = True
                return 0
            try:  # between tasks: apply a new resource profile (restarts the model servers)
                from . import serve as model_server
                model_server.apply_if_changed()
            except (Exception, SystemExit) as e:
                print(f"could not apply the resource profile: {e}", flush=True)
            if any(t["status"] in ("new", "approved") for t in w.store.list(50)):
                if not ensure_llm():
                    print("local models are not reachable; waiting", flush=True)
                    time.sleep(10)
                    continue
            if w.run_once():
                last = time.time()
                continue
            if idle_exit and time.time() - last > idle_exit:
                print("idle; exiting", flush=True)
                return 0
            time.sleep(2)
    finally:
        _release(lock)
        if restart:
            print("code or config changed; starting a fresh worker", flush=True)
            ensure_worker()


# ---------- CLI ----------

def _default_workspace():
    """The folder the person is standing in: the git root if there is one, else the cwd.

    A task given from inside a repo must apply to that repo. Defaulting to empty silently sent the work to
    .ariadne/workspace instead, where the model changed a copy nobody was looking at.
    """
    cwd = os.getcwd()
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True,
                           timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd


def _default_session(workspace: str = "") -> str:
    """A workstream is a folder: tasks given in the same repo build on each other.

    The design's default was "session = repo folder name", so a second task in the same checkout continues the
    first instead of starting a stranger every time.
    """
    name = Path(workspace or _default_workspace()).name
    return re.sub(r"[^\w.-]+", "-", name).strip("-") or "main"


def _print(t):
    print(json.dumps(t, indent=2, default=str))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ariadne", description="Ariadne tasks: brief, backbrief, sign-off, execute")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit"); s.add_argument("text", nargs="?", default="")
    s.add_argument("--file", default="", help="read the task text from a file (long briefs, no shell quoting)")
    s.add_argument("--workspace", default="", help="the folder the task applies to (default: the git root of the "
                                                   "folder you run this from, else the current folder)")
    s.add_argument("--flow", default=""); s.add_argument("--wait", type=int, default=0)
    s.add_argument("--session", default="", help="continue this Hermes session (default: a new one for the task)")
    s.add_argument("--gate", action="append", default=[], help="a check gate ('run: pytest -q' for a command); repeatable")
    s.add_argument("--json", action="store_true", help="machine output: the task row as JSON, no following")
    s.add_argument("--no-follow", action="store_true", help="return as soon as the task is queued")
    gt = sub.add_parser("gates"); gt.add_argument("id"); gt.add_argument("gates", nargs="+")
    g = sub.add_parser("get"); g.add_argument("id")
    w = sub.add_parser("wait"); w.add_argument("id"); w.add_argument("--timeout", type=int, default=600)
    a = sub.add_parser("approve"); a.add_argument("id")
    a.add_argument("--model", action="append", default=[], metavar="STEP=NAME",
                   help="change a step's model before locking the plan (STEP may be 'all'); repeatable")
    r = sub.add_parser("revise"); r.add_argument("id"); r.add_argument("feedback")
    c = sub.add_parser("cancel"); c.add_argument("id")
    f = sub.add_parser("feedback"); f.add_argument("id"); f.add_argument("text")
    sub.add_parser("list")
    sub.add_parser("sessions")
    sub.add_parser("serve")
    sub.add_parser("flows")
    args = ap.parse_args(argv)
    if args.cmd == "serve":
        return serve()
    if args.cmd == "flows":
        for name, home in flowlib.compile_all().items():
            print(f"{name}: {home}")
        return 0
    st = Store()
    if args.cmd == "submit":
        text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
        workspace = args.workspace or _default_workspace()
        tid = st.submit(text, "cli", workspace, args.flow, args.session or _default_session(workspace), args.gate)
        ensure_worker()
        if args.json:
            _print(st.wait(tid, args.wait) if args.wait else {"id": tid, "status": "new"})
        elif args.no_follow:
            print(f"{tid}: queued. Follow it with: ariadne follow {tid}")
        else:
            # The point of giving a task is to see it plan and then read the backbrief. `--json` is the escape
            # hatch for scripts; the default is the human loop the README describes.
            from . import console
            return console.follow(st, tid, timeout=args.wait or 3600)
    elif args.cmd == "get":
        _print(st.get(args.id))
    elif args.cmd == "wait":
        ensure_worker()
        _print(st.wait(args.id, args.timeout))
    elif args.cmd == "approve":
        st.approve(args.id, ",".join(args.model) or None); ensure_worker(); _print(st.get(args.id, events=False))
    elif args.cmd == "revise":
        st.revise(args.id, args.feedback); ensure_worker(); _print(st.get(args.id, events=False))
    elif args.cmd == "gates":
        st.set_gates(args.id, args.gates); ensure_worker(); _print(st.get(args.id, events=False))
    elif args.cmd == "feedback":
        st.feedback(args.id, args.text); print("feedback recorded; a larger model folds it into the flow's skills (save_skill)")
    elif args.cmd == "cancel":
        st.cancel(args.id); _print(st.get(args.id, events=False))
    elif args.cmd == "sessions":
        for s in st.sessions():
            print(f"{s['name']:<28} {s['tasks']:>3} tasks  segment {s['segment']:<3} {s['flow'] or '-':<8} "
                  f"{(s['summary'] or '').splitlines()[0][:60] if s['summary'] else ''}")
    elif args.cmd == "list":
        for t in st.list():
            print(f"{t['id']}  {t['status']:<17} {t['flow'] or '-':<8} {t['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
