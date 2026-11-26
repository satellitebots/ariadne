"""The store for durable tasks, their signed versions, drafts and runs (docs/DESIGN.md, "Durable tasks and runs").

A task is a name with signed versions; a version's spec never changes (editing makes a new draft, signing it makes
the next version). A draft is the definition while the orchestrator and the person shape it. A run is one execution
of one version: its steps, their attempts, and its events. The old `tasks.db` (a task that was also its execution)
stays as history and is not written by anything here.
"""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import paths, spec as speclib

RUN_STATUS = ("queued", "waiting", "running", "parked", "asking", "done", "failed", "timed_out", "cancelled", "needs_you")
LIVE = ("queued", "waiting", "running", "parked", "asking")   # asking: waits for a yes or no (permissions.yaml)
SCHEMA = """
CREATE TABLE IF NOT EXISTS task(id TEXT PRIMARY KEY, name TEXT UNIQUE, created REAL, updated REAL, flow TEXT,
  status TEXT, version INTEGER DEFAULT 0, scheduled INTEGER DEFAULT 1, next_due REAL, last_run TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS task_version(task_id TEXT, version INTEGER, signed REAL, spec TEXT,
  PRIMARY KEY(task_id, version));
CREATE TABLE IF NOT EXISTS draft(id TEXT PRIMARY KEY, created REAL, updated REAL, status TEXT, flow TEXT,
  task_id TEXT DEFAULT '', base_version INTEGER DEFAULT 0, spec TEXT, asks TEXT DEFAULT '{}', source TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS message(ref TEXT, ts REAL, role TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS run(id TEXT PRIMARY KEY, task_id TEXT, version INTEGER, created REAL, trigger TEXT,
  status TEXT, step INTEGER DEFAULT 0, started REAL DEFAULT 0, ended REAL DEFAULT 0, result TEXT DEFAULT '',
  error TEXT DEFAULT '', workspace TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS run_step(run_id TEXT, n INTEGER, attempt INTEGER, status TEXT, started REAL, ended REAL,
  model TEXT DEFAULT '', report TEXT DEFAULT '', gate TEXT DEFAULT '', log TEXT DEFAULT '', session TEXT DEFAULT '',
  PRIMARY KEY(run_id, n, attempt));
CREATE TABLE IF NOT EXISTS event(ts REAL, ref TEXT, kind TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS event_ref ON event(ref, ts);
CREATE TABLE IF NOT EXISTS steer(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, created REAL, text TEXT,
  consumed REAL DEFAULT 0);
"""


def _id(prefix):
    return f"{prefix}{time.strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


class Store:
    def __init__(self, db_path=None):
        self.db_path = str(db_path or paths.STATE / "ariadne.db")
        self.specs_dir = Path(self.db_path).parent / "tasks"
        with self._conn() as c:
            c.executescript(SCHEMA)
            cols = {r["name"] for r in c.execute("PRAGMA table_info(run)")}
            if "plan" not in cols:      # added 26 Nov: a run's own steps once `each:` steps are expanded
                c.execute("ALTER TABLE run ADD COLUMN plan TEXT DEFAULT ''")

    @contextmanager
    def _conn(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    def _one(self, sql, *a):
        with self._conn() as c:
            r = c.execute(sql, a).fetchone()
        return dict(r) if r else None

    def _all(self, sql, *a):
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, a)]

    def _exec(self, sql, *a):
        with self._conn() as c:
            return c.execute(sql, a)

    # ---------- events and messages ----------
    def event(self, ref, kind, detail=""):
        self._exec("INSERT INTO event(ts, ref, kind, detail) VALUES (?,?,?,?)", time.time(), ref, kind,
                   str(detail)[:8000])
        try:
            from .activity import log
            log(ref, f"{kind}: {detail}")
        except Exception:
            pass          # the activity log is a convenience; the store is the record

    def events(self, ref=None, since=0.0, limit=500, newest=False):
        """Events in time order; `newest`: the last `limit` of them (a busy run logs every tool call)."""
        order = "DESC" if newest else ""
        if ref:
            rows = self._all(f"SELECT * FROM event WHERE ref=? AND ts>? ORDER BY ts {order}, rowid {order} LIMIT ?",
                             ref, since, limit)
        else:
            rows = self._all(f"SELECT * FROM event WHERE ts>? ORDER BY ts {order}, rowid {order} LIMIT ?", since, limit)
        return rows[::-1] if newest else rows

    def message(self, ref, role, text):
        self._exec("INSERT INTO message(ref, ts, role, text) VALUES (?,?,?,?)", ref, time.time(), role, text)

    def messages(self, ref):
        return self._all("SELECT role, text, ts FROM message WHERE ref=? ORDER BY ts", ref)

    # ---------- drafts ----------
    def draft_new(self, flow, spec, asks=None, task_id="", base_version=0, source=""):
        did = _id("d")
        now = time.time()
        self._exec("INSERT INTO draft(id, created, updated, status, flow, task_id, base_version, spec, asks, source) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", did, now, now, "open", flow, task_id, base_version,
                   json.dumps(spec), json.dumps(asks or {}), source)
        self.event(did, "draft", f"opened for flow {flow}" + (f" from {task_id} v{base_version}" if task_id else ""))
        return did

    def draft(self, did):
        d = self._one("SELECT * FROM draft WHERE id=?", did)
        if d:
            d["spec"], d["asks"] = json.loads(d["spec"] or "{}"), json.loads(d["asks"] or "{}")
        return d

    def draft_set(self, did, spec):
        self._exec("UPDATE draft SET spec=?, updated=? WHERE id=?", json.dumps(spec), time.time(), did)

    def draft_close(self, did, status):
        self._exec("UPDATE draft SET status=?, updated=? WHERE id=?", status, time.time(), did)

    def drafts(self, status="open"):
        return [self.draft(r["id"]) for r in self._all("SELECT id FROM draft WHERE status=? ORDER BY updated DESC", status)]

    # ---------- tasks ----------
    def sign(self, spec, task_id=""):
        """Store `spec` (already validated) as the next version of its task, creating the task on its first version."""
        now = time.time()
        t = self.task(task_id) if task_id else self.task_by_name(spec["name"])
        if t is None:
            task_id = _id("t")
            self._exec("INSERT INTO task(id, name, created, updated, flow, status, version) VALUES (?,?,?,?,?,?,0)",
                       task_id, spec["name"], now, now, spec["flow"], "signed")
            t = self.task(task_id)
        v = t["version"] + 1
        self._exec("INSERT INTO task_version(task_id, version, signed, spec) VALUES (?,?,?,?)",
                   t["id"], v, now, json.dumps(spec))
        due = speclib.next_due(spec, now - 1)
        self._exec("UPDATE task SET version=?, updated=?, name=?, flow=?, status='signed', next_due=? WHERE id=?",
                   v, now, spec["name"], spec["flow"], due, t["id"])
        f = self.specs_dir / t["id"] / f"v{v}.yaml"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(speclib.dump(spec), encoding="utf-8")
        self.event(t["id"], "sign", f"version {v} signed ({speclib.describe_trigger(spec)})")
        return t["id"], v

    def task(self, tid):
        return self._one("SELECT * FROM task WHERE id=?", tid)

    def task_by_name(self, name):
        return self._one("SELECT * FROM task WHERE name=?", name)

    def find_task(self, ref):
        return self.task(ref) or self.task_by_name(ref)

    def tasks(self, include_retired=False):
        q = "SELECT * FROM task" + ("" if include_retired else " WHERE status!='retired'") + " ORDER BY updated DESC"
        return self._all(q)

    def spec(self, tid, version=None):
        t = self.task(tid)
        if not t:
            return None
        r = self._one("SELECT spec FROM task_version WHERE task_id=? AND version=?", tid, version or t["version"])
        return json.loads(r["spec"]) if r else None

    def task_set(self, tid, **f):
        f["updated"] = time.time()
        self._exec(f"UPDATE task SET {', '.join(k + '=?' for k in f)} WHERE id=?", *f.values(), tid)

    def due(self, now):
        return self._all("SELECT * FROM task WHERE status='signed' AND scheduled=1 AND next_due IS NOT NULL "
                         "AND next_due<=? ORDER BY next_due", now)

    # ---------- runs ----------
    def run_new(self, tid, trigger="manual"):
        t = self.task(tid)
        sp = self.spec(tid)
        rid = _id("r")
        self._exec("INSERT INTO run(id, task_id, version, created, trigger, status, workspace) VALUES (?,?,?,?,?,?,?)",
                   rid, tid, t["version"], time.time(), trigger, "queued", sp.get("workspace", ""))
        self.task_set(tid, last_run=rid)
        self.event(rid, "queued", f"{t['name']} v{t['version']} ({trigger})")
        return rid

    def run(self, rid):
        return self._one("SELECT * FROM run WHERE id=?", rid)

    def runs(self, tid=None, live=False, limit=50):
        q, a = "SELECT * FROM run WHERE 1=1", []
        if tid:
            q, a = q + " AND task_id=?", a + [tid]
        if live:
            q += f" AND status IN ({','.join('?' * len(LIVE))})"
            a += list(LIVE)
        return self._all(q + " ORDER BY created DESC LIMIT ?", *a, limit)

    def run_plan(self, rid):
        """The run's own steps once an `each:` step was expanded, else None (the signed spec's steps)."""
        r = self._one("SELECT plan FROM run WHERE id=?", rid)
        return json.loads(r["plan"]) if r and r["plan"] else None

    def run_plan_set(self, rid, steps):
        self._exec("UPDATE run SET plan=? WHERE id=?", json.dumps(steps), rid)

    def run_set(self, rid, **f):
        self._exec(f"UPDATE run SET {', '.join(k + '=?' for k in f)} WHERE id=?", *f.values(), rid)

    def claim(self):
        """The oldest queued run, now `waiting` for the machine (FIFO by creation, never reordered by a touch)."""
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            r = c.execute("SELECT * FROM run WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if r:
                c.execute("UPDATE run SET status='waiting' WHERE id=?", (r["id"],))
            c.execute("COMMIT")
        return dict(r) if r else None

    def step_set(self, rid, n, attempt, **f):
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO run_step(run_id, n, attempt, status, started) VALUES (?,?,?,?,?)",
                      (rid, n, attempt, "running", time.time()))
            if f:
                c.execute(f"UPDATE run_step SET {', '.join(k + '=?' for k in f)} WHERE run_id=? AND n=? AND attempt=?",
                          (*f.values(), rid, n, attempt))

    def steps(self, rid):
        return self._all("SELECT * FROM run_step WHERE run_id=? ORDER BY n, attempt", rid)

    # ---------- steering ----------
    def steer(self, rid, text):
        self._exec("INSERT INTO steer(run_id, created, text) VALUES (?,?,?)", rid, time.time(), text)
        self.event(rid, "steer", f"note queued: {text[:200]}")

    def steers(self, rid):
        """Every note for a run, oldest first. They hold for the rest of the run: each later step is given all of them."""
        return [r["text"] for r in self._all("SELECT text FROM steer WHERE run_id=? ORDER BY id", rid)]

    def take_steers(self, rid):
        rows = self._all("SELECT id, text FROM steer WHERE run_id=? AND consumed=0 ORDER BY id", rid)
        for r in rows:
            self._exec("UPDATE steer SET consumed=? WHERE id=?", time.time(), r["id"])
        return [r["text"] for r in rows]
