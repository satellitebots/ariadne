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
from . import llm, paths
from .memory import Memory, format_hits

FINAL = ("done", "failed", "cancelled")
WAITING = ("awaiting_signoff", "needs_attention")   # the task needs the person who gave it
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, created REAL, updated REAL, source TEXT, text TEXT, workspace TEXT, flow TEXT,
  status TEXT, plan TEXT DEFAULT '', feedback TEXT DEFAULT '', result TEXT DEFAULT '', error TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS events(task_id TEXT, ts REAL, kind TEXT, detail TEXT);
"""


class TaskError(ValueError):
    pass


class Store:
    def __init__(self, db_path=None):
        self.db_path = str(db_path or paths.TASKS_DB)
        if db_path is None:
            paths.ensure()
        with self._conn() as c:
            c.executescript(SCHEMA)

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

    def submit(self, text, source="cli", workspace="", flow=""):
        text = (text or "").strip()
        if not text:
            raise TaskError("the task text is empty")
        tid = time.strftime("t%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        now = time.time()
        with self._conn() as c:
            c.execute("INSERT INTO tasks(id, created, updated, source, text, workspace, flow, status) "
                      "VALUES (?,?,?,?,?,?,?,?)", (tid, now, now, source, text, workspace or "", flow or "", "new"))
        self.event(tid, "brief", f"from {source}: {text[:300]}")
        return tid

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

    def approve(self, tid):
        self._transition(tid, ("awaiting_signoff",), "approved")
        self.event(tid, "sign-off", "approved")

    def revise(self, tid, feedback):
        t = self.get(tid, events=False)
        fb = (t["feedback"] + "\n" if t["feedback"] else "") + feedback.strip()
        self._transition(tid, WAITING, "new", feedback=fb)
        self.event(tid, "sign-off", f"revise: {feedback[:300]}")

    def cancel(self, tid):
        self._transition(tid, ("new", "awaiting_signoff", "approved", "needs_attention"), "cancelled")
        self.event(tid, "sign-off", "cancelled")

    def claim_next(self):
        """Oldest task that needs the worker: new -> planning, approved -> executing (atomic)."""
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            r = c.execute("SELECT id, status FROM tasks WHERE status IN ('new','approved') "
                          "ORDER BY updated LIMIT 1").fetchone()
            if not r:
                c.execute("COMMIT")
                return None
            to = "planning" if r["status"] == "new" else "executing"
            c.execute("UPDATE tasks SET status=?, updated=? WHERE id=?", (to, time.time(), r["id"]))
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


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _clean_output(out):
    """Hermes -Q prints tool previews (boxed, coloured diffs), the answer, then session info; keep the answer."""
    lines = []
    for l in _ANSI.sub("", out).splitlines():
        if re.match(r"^\s*(session[ _]?id|session:|resume with)", l, re.I) or l.lstrip().startswith("│"):
            continue
        lines.append(l)
    return "\n".join(lines).strip()


def hermes_run(flow, phase, prompt, workspace, tid):
    """One headless Hermes run in the flow's worker home."""
    home = flow.home
    (home / "ariadne_phase").write_text(phase, encoding="utf-8")
    qfile = paths.LOGS / f"{tid}-{phase}-{int(time.time())}.prompt.md"
    qfile.write_text(prompt, encoding="utf-8")
    # Hermes names an MCP server's toolset "mcp-<server>" (the bare name can collide with a built-in, e.g. memory).
    toolsets = (flow.plan_toolsets if phase == "plan" else flow.execute_toolsets) + [f"mcp-{m}" for m in flow.mcp_servers]
    cmd = [str(paths.HERMES_EXE), "chat", "--query-file", str(qfile), "-Q", "--source", "tool",
           "--max-turns", str(flow.max_turns[phase]), "--run-budget", str(flow.run_budget[phase]),
           "-t", ",".join(toolsets)]
    for s in flow.skills:
        cmd += ["-s", s]
    env = dict(os.environ, HERMES_HOME=str(home), PYTHONIOENCODING="utf-8")
    env.pop("ARIADNE_GUARD_ALL_PROCS", None)
    log = qfile.with_suffix("").with_suffix(".log")
    try:
        p = subprocess.run(cmd, cwd=workspace, env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=flow.run_budget[phase] + 180,
                           stdin=subprocess.DEVNULL)
        out, code = p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr.strip() else ""), p.returncode
    except subprocess.TimeoutExpired as e:
        out, code = f"(timed out)\n{e.stdout or ''}", 124
    log.write_text(" ".join(cmd) + "\n\n" + out, encoding="utf-8")
    return RunResult(_clean_output(p.stdout if code != 124 else out), code, str(log))


# ---------- prompts ----------

PLAN_PROMPT = """You are the {flow} worker of Ariadne, a local agent harness. This is the PLAN phase: you may only read
(files, search, shared memory, git status/diff/log). Nothing is changed until a person approves your plan.

TASK (from {source}):
{text}

WORKSPACE: {workspace}
{feedback}
SHARED MEMORY (what earlier tasks recorded):
{memory}

After sign-off the execute phase will have only these tools: {exec_tools}. Plan only steps those tools can do.

Investigate just enough to plan well (look at the relevant files). Then reply with a backbrief in exactly this form:

MISSION: <one sentence: what will be true when this is done>
FLOW: {flow}
STEPS:
1. <step> - tools: <tools it uses>
2. ...
CHECKS: <how we will know it worked>
RISKS: <what could go wrong, or 'none'>
QUESTIONS: <anything the person must answer first, or 'none'>
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
- At the end, record in shared memory (memory_record) anything a later task should know about this workspace.
- Finish with a short report: what you changed, how you verified it.
"""

ROUTE_PROMPT = """Pick the flow for this task. Flows:
{flows}

Task: {text}

Reply with only the flow name."""


# ---------- the worker ----------

class Worker:
    def __init__(self, store=None, memory=None, flows=None, runner=hermes_run, router_model="router", llm_chat=None):
        self.store = store or Store()
        self.memory = memory or Memory()
        self.flows = flows or flowlib.load_flows()
        self.runner = runner
        self.router_model = router_model
        self.llm_chat = llm_chat or llm.chat

    def route(self, t):
        if t["flow"] in self.flows:
            return t["flow"], "given by the task"
        if len(self.flows) == 1:
            return next(iter(self.flows)), "only flow"
        listing = "\n".join(f"- {f.name}: {f.when}" for f in self.flows.values())
        try:
            answer = self.llm_chat(self.router_model, [{"role": "user", "content": ROUTE_PROMPT.format(
                flows=listing, text=t["text"])}]).lower()
        except Exception as e:  # router down: fall back, say so
            answer = ""
            self.store.event(t["id"], "route", f"router failed ({e}); using the first flow")
        for name in self.flows:
            if re.search(rf"\b{re.escape(name)}\b", answer):
                return name, f"router said '{answer[:60]}'"
        return next(iter(self.flows)), f"router answer '{answer[:60]}' named no flow; using the first flow"

    def workspace(self, t):
        ws = t["workspace"] or str(paths.STATE / "workspace")
        Path(ws).mkdir(parents=True, exist_ok=True)
        return ws

    def plan(self, t):
        name, why = self.route(t)
        flow = self.flows[name]
        self.store.update(t["id"], flow=name)
        self.store.event(t["id"], "route", f"{name} ({why})")
        ws = self.workspace(t)
        hits = self.memory.recall(f"{t['text']} {ws}", limit=5)
        feedback = f"\nFEEDBACK ON THE LAST PLAN (address it):\n{t['feedback']}\n" if t["feedback"] else ""
        prompt = PLAN_PROMPT.format(flow=name, source=t["source"], text=t["text"], workspace=ws,
                                    feedback=feedback, memory=format_hits(hits),
                                    exec_tools=", ".join(flow.execute_toolsets + [f"{m} (MCP)" for m in flow.mcp_servers]))
        self.store.event(t["id"], "plan", f"started ({len(hits)} memories recalled)")
        r = self.runner(flow, "plan", prompt, ws, t["id"])
        if r.exit_code != 0 or not r.text:
            self.store.update(t["id"], status="failed", error=f"plan run failed (exit {r.exit_code}); log {r.log}")
            self.store.event(t["id"], "plan", f"failed, log {r.log}")
            return
        self.store.update(t["id"], status="awaiting_signoff", plan=r.text)
        self.store.event(t["id"], "backbrief", "ready for sign-off")
        self.memory.record("task", t["id"], f"{t['text']}\nstatus: awaiting sign-off",
                           [("uses_flow", "flow", name), ("in_workspace", "workspace", ws)])

    def run_checks(self, flow, ws):
        failures = []
        for check in flow.checks:
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

    def execute(self, t):
        flow = self.flows.get(t["flow"])
        if not flow:
            self.store.update(t["id"], status="failed", error=f"flow '{t['flow']}' no longer exists")
            return
        ws = self.workspace(t)
        extra, attempts = "", 0
        while True:
            attempts += 1
            self.store.event(t["id"], "execute", f"attempt {attempts}")
            r = self.runner(flow, "execute", EXEC_PROMPT.format(flow=flow.name, text=t["text"], workspace=ws,
                                                                 plan=t["plan"], extra=extra), ws, t["id"])
            if r.exit_code != 0 or not r.text:
                return self._finish(t, flow, ws, "failed", r.text, f"execute run failed (exit {r.exit_code}); log {r.log}")
            if r.text.lstrip().upper().startswith("OFF-PLAN"):
                self.store.update(t["id"], status="needs_attention", result=r.text)
                self.store.event(t["id"], "execute", "stopped: off-plan, back to the person for a new sign-off")
                return
            failures = self.run_checks(flow, ws)
            if not failures:
                self.store.event(t["id"], "checks", "passed" if flow.checks else "none defined")
                return self._finish(t, flow, ws, "done", r.text)
            self.store.event(t["id"], "checks", f"failed: {failures[0][:300]}")
            if attempts >= 2:
                return self._finish(t, flow, ws, "failed", r.text, "checks still failing:\n" + "\n".join(failures))
            extra = ("\nA PREVIOUS ATTEMPT FINISHED BUT THESE CHECKS FAILED. Fix them, staying on the plan:\n"
                     + "\n".join(failures) + "\n")

    def _finish(self, t, flow, ws, status, result, error=""):
        self.store.update(t["id"], status=status, result=result or "", error=error)
        self.store.event(t["id"], "report", status + (f": {error[:300]}" if error else ""))
        self.memory.record("task", t["id"], f"{t['text']}\nstatus: {status}\nresult: {(result or error)[:1500]}",
                           [("uses_flow", "flow", flow.name), ("in_workspace", "workspace", ws)])

    def run_once(self):
        t = self.store.claim_next()
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
    f = _try_lock(LOCK)
    if f is None:
        return True
    _release(f)
    return False


def ensure_worker():
    """Start the worker process if none is running (detached; its own log; no pipes to the caller)."""
    if os.environ.get("ARIADNE_NO_AUTOSTART") or worker_running():
        return False
    paths.ensure()
    log = open(paths.LOGS / "worker.log", "a", encoding="utf-8")
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen([str(paths.PYTHON), "-m", "ariadne.orchestrator", "serve"], cwd=str(paths.ROOT),
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags, close_fds=True,
                     env=dict(os.environ, PYTHONPATH=str(paths.ROOT)))
    return True


def ensure_llm(wait=120):
    if llm.is_up():
        return True
    serve = paths.ROOT / "tools" / "serve.ps1"
    print(f"llama-swap is down; starting it with {serve}", flush=True)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(serve)],
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
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
    subprocess.run([str(paths.HERMES_EXE), "gateway", "stop"], env=dict(os.environ, HERMES_HOME=str(home)),
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=120)


def serve(idle_exit=1800):
    lock = _try_lock(LOCK)
    if lock is None:
        print("another Ariadne worker is running", flush=True)
        return 2
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} worker up (pid {os.getpid()})", flush=True)
    for name, home in flowlib.compile_all().items():
        print(f"  flow {name} -> {home}", flush=True)
        stop_gateway(home)  # a gateway left from an earlier worker still has the old config; the next run restarts it
    w, last = Worker(), time.time()
    try:
        while True:
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


# ---------- CLI ----------

def _print(t):
    print(json.dumps(t, indent=2, default=str))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ariadne", description="Ariadne tasks: brief, backbrief, sign-off, execute")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit"); s.add_argument("text", nargs="?", default="")
    s.add_argument("--file", default="", help="read the task text from a file (long briefs, no shell quoting)")
    s.add_argument("--workspace", default="")
    s.add_argument("--flow", default=""); s.add_argument("--wait", type=int, default=0)
    g = sub.add_parser("get"); g.add_argument("id")
    w = sub.add_parser("wait"); w.add_argument("id"); w.add_argument("--timeout", type=int, default=600)
    a = sub.add_parser("approve"); a.add_argument("id")
    r = sub.add_parser("revise"); r.add_argument("id"); r.add_argument("feedback")
    c = sub.add_parser("cancel"); c.add_argument("id")
    sub.add_parser("list")
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
        tid = st.submit(text, "cli", args.workspace, args.flow)
        ensure_worker()
        _print(st.wait(tid, args.wait) if args.wait else {"id": tid, "status": "new"})
    elif args.cmd == "get":
        _print(st.get(args.id))
    elif args.cmd == "wait":
        ensure_worker()
        _print(st.wait(args.id, args.timeout))
    elif args.cmd == "approve":
        st.approve(args.id); ensure_worker(); _print(st.get(args.id, events=False))
    elif args.cmd == "revise":
        st.revise(args.id, args.feedback); ensure_worker(); _print(st.get(args.id, events=False))
    elif args.cmd == "cancel":
        st.cancel(args.id); _print(st.get(args.id, events=False))
    elif args.cmd == "list":
        for t in st.list():
            print(f"{t['id']}  {t['status']:<17} {t['flow'] or '-':<8} {t['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
