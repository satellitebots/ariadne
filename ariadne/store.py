"""The task store: tasks, events and sessions in one sqlite file - the single source of truth.

Every surface reads the same rows and every write is a store write plus an event, so the terminal, MCP, the chat and
the UI cannot disagree about what happened. The rules about *who may do what* live in `service.py`; nothing here
decides, it records. `worker.py` is the only module that writes progress while a task runs.
"""
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import paths
from .errors import TaskError


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
CREATE TABLE IF NOT EXISTS schedules(
  name TEXT PRIMARY KEY, cron TEXT, brief TEXT, flow TEXT, model TEXT, workspace TEXT, gates TEXT DEFAULT '[]',
  enabled INTEGER DEFAULT 1, created REAL, last_run REAL DEFAULT 0, last_task TEXT DEFAULT '');
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

    def events_since(self, since=0.0, limit=200):
        """Task events newer than `since` (a timestamp), oldest first: what SSE streams and the UI appends."""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT task_id, ts, kind, detail FROM events WHERE ts > ? ORDER BY ts LIMIT ?",
                (float(since or 0), int(limit)))]

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
                "SELECT id, status, flow, source, session, substr(text,1,80) AS text, updated FROM tasks "
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
        # The model plan's own functions live in `worker.py`; imported here so `store` does not import `worker` at
        # load time (the worker imports the store, and this is the only rule the store needs from it).
        from .worker import apply_model_overrides, model_summary
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

    # ---------- schedules: a standing brief, not a new kind of job ----------

    def schedules(self, enabled_only=False):
        with self._conn() as c:
            q = "SELECT * FROM schedules" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY name"
            return [dict(r) for r in c.execute(q)]

    def schedule(self, name):
        with self._conn() as c:
            r = c.execute("SELECT * FROM schedules WHERE name=?", (name,)).fetchone()
        if not r:
            raise TaskError(f"no schedule {name}")
        return dict(r)

    def schedule_create(self, name, cron, brief, flow, model, workspace="", gates=(), now=None):
        """A schedule inherits the session's flow, model, workspace and gates; creating it is the standing authorisation."""
        now = time.time() if now is None else now
        name = (name or "").strip()
        if not name:
            raise TaskError("a schedule needs a name (it is also the session its runs continue)")
        if not (brief or "").strip():
            raise TaskError("a schedule needs a brief: what should be true when a run is done?")
        with self._conn() as c:
            if c.execute("SELECT 1 FROM schedules WHERE name=?", (name,)).fetchone():
                raise TaskError(f"schedule {name} already exists; edit it instead of creating it twice")
            c.execute("INSERT INTO schedules(name, cron, brief, flow, model, workspace, gates, enabled, created, "
                      "last_run) VALUES (?,?,?,?,?,?,?,1,?,0)",
                      (name, cron, brief.strip(), flow, model, workspace or "",
                       json.dumps([gate(g) if isinstance(g, str) else g for g in gates]), now))
        return self.schedule(name)

    def schedule_update(self, name, **fields):
        allowed = {k: v for k, v in fields.items() if k in ("cron", "brief", "flow", "model", "workspace", "gates",
                                                            "enabled")}
        if not allowed:
            raise TaskError("nothing to change")
        if "gates" in allowed and not isinstance(allowed["gates"], str):
            allowed["gates"] = json.dumps([gate(g) if isinstance(g, str) else g for g in allowed["gates"]])
        with self._conn() as c:
            c.execute(f"UPDATE schedules SET {', '.join(k + '=?' for k in allowed)} WHERE name=?",
                      (*allowed.values(), name))
        return self.schedule(name)

    def schedule_ran(self, name, when, task_id):
        with self._conn() as c:
            c.execute("UPDATE schedules SET last_run=?, last_task=? WHERE name=?", (when, task_id, name))

    def schedule_delete(self, name):
        with self._conn() as c:
            c.execute("DELETE FROM schedules WHERE name=?", (name,))

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
