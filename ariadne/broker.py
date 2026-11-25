"""The broker: the one owner of the machine (docs/DESIGN.md, "The broker").

One GPU and one RAM budget cannot hold the orchestrator, a worker, a job and the embedder at once. Every failure in
the November runs came from them loading models behind each other's backs. So nothing loads or unloads a model
except through a lease from here:

- **One lease, one holder.** The orchestrator (a draft conversation), a worker (a run's step) or a job. Everyone else
  waits in a FIFO queue that every front shows (`status()`).
- **Handoffs at boundaries only.** A holder gives the machine up when it releases, or at a boundary where someone is
  waiting (`Lease.boundary()`), never mid-generation. Parking (park.py) makes the boundary come sooner.
- **Same weights, no reload.** Switching to a model that is already loaded is free; anything else unloads first and
  checks the server really is empty before the next model is requested.
- **The broker starts the model server** when a holder needs it, so no caller assumes it is up.

State is a small SQLite file shared by every process (worker, console, MCP server, chat). A holder whose process died
loses the lease on the next look.
"""
import json
import os
import sqlite3
import time
import urllib.request
from contextlib import contextmanager

from . import paths

KINDS = ("orchestrator", "worker", "job")
SCHEMA = """
CREATE TABLE IF NOT EXISTS lease(id INTEGER PRIMARY KEY CHECK (id = 1), kind TEXT, ref TEXT, model TEXT, pid INTEGER,
  since REAL, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS queue(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref TEXT, model TEXT, pid INTEGER,
  requested REAL, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS loaded(id INTEGER PRIMARY KEY CHECK (id = 1), model TEXT, since REAL);
"""


def _alive(pid):
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:
        return True   # cannot tell: never steal a lease on a guess


class Server:
    """What the broker needs from the model server (llama-swap). Tests pass a fake with the same four methods."""

    def __init__(self, base=None):
        self._base = base

    def base(self):
        if self._base:
            return self._base
        from . import serving
        return serving.base()

    def up(self):
        try:
            urllib.request.urlopen(self.base() + "/health", timeout=3).read()
            return True
        except Exception:
            return False

    def start(self):
        from . import serve
        serve.start()

    def running(self):
        """Names of the models loaded now (llama-swap /running); [] when nothing is loaded or it cannot say."""
        try:
            with urllib.request.urlopen(self.base() + "/running", timeout=5) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return []
        rows = data.get("running", data) if isinstance(data, dict) else data
        return [r.get("model", "") for r in rows if isinstance(r, dict) and r.get("state", "ready") != "stopped"]

    def unload(self):
        try:
            urllib.request.urlopen(self.base() + "/unload", timeout=60).read()
            return True
        except Exception:
            return False


class Busy(RuntimeError):
    """acquire(wait=False) when someone else holds the machine."""


class Lease:
    def __init__(self, broker, kind, ref, model):
        self.broker, self.kind, self.ref, self.model = broker, kind, ref, model
        self.held = True

    def boundary(self):
        """At a step boundary: is anyone waiting? The holder then releases and queues again (`yield_turn`)."""
        return self.held and bool(self.broker.waiting())

    def yield_turn(self, note=""):
        """Give the machine to whoever waits, then wait for it back. Returns True if it actually changed hands."""
        if not self.boundary():
            return False
        self.release()
        again = self.broker.acquire(self.kind, self.ref, self.model, note=note or "back after yielding")
        self.held, self.model = True, again.model
        return True

    def switch(self, model, kind=None):
        """Same holder, another model (a step on another model, or a job: model=None unloads everything)."""
        self.broker._prepare(model)
        self.model, self.kind = model, kind or self.kind
        self.broker._set_holder(self.kind, self.ref, model)

    def release(self):
        if self.held:
            self.broker._release(self.ref)
            self.held = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


class Broker:
    def __init__(self, db_path=None, server=None, poll=0.5, log=None):
        self.db_path = str(db_path or paths.STATE / "machine.db")
        self.server = server or Server()
        self.poll = poll
        self.log = log or (lambda msg: None)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    # ---------- the lease ----------
    def acquire(self, kind, ref, model, note="", wait=True, timeout=None, on_wait=None):
        """Join the queue and return a Lease once this request is first and the machine is free.

        `model` is the catalog name the holder will call (None for a job: everything is unloaded). `on_wait(status)`
        is called once when the request has to wait, so a front can say who holds the machine.
        """
        assert kind in KINDS, kind
        pid = os.getpid()
        with self._conn() as c:
            qid = c.execute("INSERT INTO queue(kind, ref, model, pid, requested, note) VALUES (?,?,?,?,?,?)",
                            (kind, ref, model or "", pid, time.time(), note)).lastrowid
        deadline = None if timeout is None else time.time() + timeout
        told = False
        try:
            while True:
                if self._try_take(qid, kind, ref, model, pid, note):
                    break
                if not wait:
                    raise Busy(self.describe())
                if not told and on_wait:
                    on_wait(self.status())
                    told = True
                if deadline and time.time() > deadline:
                    raise TimeoutError(f"waited {timeout} s for the machine: {self.describe()}")
                time.sleep(self.poll)
        except BaseException:
            with self._conn() as c:
                c.execute("DELETE FROM queue WHERE id=?", (qid,))
            raise
        self._prepare(model)
        self.log(f"machine: {kind} {ref} holds it ({model or 'no model'})")
        return Lease(self, kind, ref, model)

    def _try_take(self, qid, kind, ref, model, pid, note):
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                h = c.execute("SELECT * FROM lease WHERE id=1").fetchone()
                if h and not _alive(h["pid"]):
                    self.log(f"machine: {h['kind']} {h['ref']} died holding it; lease freed")
                    c.execute("DELETE FROM lease WHERE id=1")
                    h = None
                # Drop queue rows of dead processes so they cannot block the line.
                for q in c.execute("SELECT id, pid FROM queue").fetchall():
                    if not _alive(q["pid"]):
                        c.execute("DELETE FROM queue WHERE id=?", (q["id"],))
                first = c.execute("SELECT id FROM queue ORDER BY id LIMIT 1").fetchone()
                if h is None and first and first["id"] == qid:
                    c.execute("INSERT INTO lease(id, kind, ref, model, pid, since, note) VALUES (1,?,?,?,?,?,?)",
                              (kind, ref, model or "", pid, time.time(), note))
                    c.execute("DELETE FROM queue WHERE id=?", (qid,))
                    c.execute("COMMIT")
                    return True
                c.execute("COMMIT")
                return False
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def _set_holder(self, kind, ref, model):
        with self._conn() as c:
            c.execute("UPDATE lease SET kind=?, model=? WHERE id=1 AND ref=?", (kind, model or "", ref))

    def _release(self, ref):
        with self._conn() as c:
            c.execute("DELETE FROM lease WHERE id=1 AND ref=?", (ref,))
        self.log(f"machine: {ref} released it")

    def waiting(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM queue ORDER BY id")]

    def holder(self):
        with self._conn() as c:
            h = c.execute("SELECT * FROM lease WHERE id=1").fetchone()
        return dict(h) if h and _alive(h["pid"]) else None

    # ---------- the model server ----------
    def _prepare(self, model):
        """Make the server ready for `model`: start it if needed; unload anything else that is loaded."""
        if not self.server.up():
            self.log("machine: model server not answering; starting it")
            self.server.start()
        loaded = [m for m in self.server.running() if m]
        if model and loaded == [model]:
            return "same weights; nothing to switch"
        if loaded:
            self.server.unload()
            for _ in range(30):
                if not [m for m in self.server.running() if m]:
                    break
                time.sleep(1)
            else:
                raise RuntimeError(f"the model server still has {loaded} loaded after unload")
            self.log(f"machine: unloaded {', '.join(loaded)}")
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO loaded(id, model, since) VALUES (1,?,?)", (model or "", time.time()))
        return f"ready for {model}" if model else "everything unloaded"

    # ---------- what the fronts show ----------
    def status(self):
        h = self.holder()
        now = time.time()
        return {
            "holder": h and {"kind": h["kind"], "ref": h["ref"], "model": h["model"],
                             "for_s": round(now - h["since"]), "note": h["note"]},
            "waiting": [{"kind": q["kind"], "ref": q["ref"], "model": q["model"],
                         "waited_s": round(now - q["requested"]), "note": q["note"]} for q in self.waiting()],
        }

    def describe(self):
        s = self.status()
        if not s["holder"]:
            return "the machine is free"
        h = s["holder"]
        line = f"{h['kind']} {h['ref']} holds the machine ({h['model'] or 'no model'}, {h['for_s']} s)"
        if s["waiting"]:
            line += "; waiting: " + ", ".join(f"{w['kind']} {w['ref']}" for w in s["waiting"])
        return line


_default = None


def default():
    global _default
    if _default is None or _default.db_path != str(paths.STATE / "machine.db"):
        _default = Broker()
    return _default
