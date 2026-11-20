"""Task orchestrator: the store, the worker process and the CLI.

    brief -> route (the flow is explicit) -> plan (Hermes worker, read-only tools)
          -> backbrief (sent back to whoever gave the task) -> sign-off (approve / revise / cancel)
          -> execute (the worker, one Hermes session per task) -> checks (gates at the edge) -> report

One worker process (`python -m ariadne.orchestrator serve`) does all the runs, one at a time, so only one model is
ever on the GPU. Tasks live in .ariadne/tasks.db; MCP servers and the CLI only read and write that table and make
sure the worker is running. Execution itself lives in `worker.py`; this module is the store and the loop around it.
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
from pathlib import Path

from . import flows as flowlib
from . import jobs, llm, park, paths
from .errors import TaskError
# The worker is a lower layer (it does not import this module at load time). These names stay importable from here
# because every surface and test has always reached for them through `ariadne.orchestrator`.
from .worker import (Worker, RunResult, hermes_run, stop_gateway, gates_text, _clean_output,   # noqa: F401
                     PARKED, _turn_end_reason, parse_model_plan, apply_model_overrides, model_summary,
                     needed_models, needed_servers, missing_servers, model_block, chain_for,
                     RESUME_PROMPT, JOBS_RULE, jobs_rule, skills_block, step_scope, _install_system_tools,
                     _reload_models, missing_system, missing_tools)

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


def _watchdog(store):
    """Start the babysitter for as long as this worker lives; returns its stop function.

    A script, never a model: it samples RAM/VRAM/health on an interval and escalates warn -> unload -> kill ->
    `needs_attention` with the readings, logging every sample (docs/COVERAGE.md, the runtime contract).
    """
    from . import watchdog
    stop = watchdog.start(store)
    print(f"watchdog: every {watchdog.INTERVAL:g} s, log {watchdog.LOG}", flush=True)
    return stop


def serve(idle_exit=1800):
    from .deps import require
    from . import local_only
    require()
    bad = local_only.check_home()
    if bad:
        # Re-checked at launch, not only when the profile was written: inference stays on this machine or the LAN.
        print("refusing to start: inference must stay local:\n  - " + "\n  - ".join(bad), flush=True)
        return 2
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
    stop_dog = _watchdog(w.store)
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
        stop_dog()
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
