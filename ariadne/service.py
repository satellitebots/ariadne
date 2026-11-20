"""One rulebook. Every surface - MCP, chat, the UI, the CLI - calls these and none of them own a rule.

The rules are the ones the design states: an approved flow, an explicitly chosen agent model, gates before work,
and no surface may accept what another would refuse. Presentation is not here; see `present.py`. The store is
reached only from here (and from the worker, which records progress while a task runs): a surface holds at most a
store handle to pass in, it never calls a store method itself.
"""
import json
from pathlib import Path

from . import flows as flowlib
from . import models as modellib
from .orchestrator import worker_running
from .paths import STATE
from .store import FINAL, WAITING, Store, TaskError

_store = None


def store():
    global _store
    if _store is None:
        _store = Store(STATE / "tasks.db")
    return _store


def _db(s=None):
    """The store to use: the one passed in (tests, an alternate home), else this process's."""
    return s or store()


def choices():
    """What the person may choose: approved flows, and the agent models the policy allows."""
    try:
        flows = [{"name": f.name, "when": f.when} for f in flowlib.load_flows().values()]
    except Exception as e:  # a broken flow file must not make every surface fail silently
        raise TaskError(f"the approved flows cannot be read: {e}")
    try:
        cat = modellib.load()
        models = [{"name": m.name, "kind": m.kind, "about": m.about, "size_gb": m.size_gb,
                   "installed": m.installed()} for m in cat.models.values() if m.kind == "agent"]
    except modellib.ModelError as e:
        raise TaskError(str(e))
    return {"flows": flows, "models": models}


def busy(store=None):
    """The machine belongs to a task: a live worker owns one in planning/executing."""
    from . import orchestrator
    if not orchestrator.worker_running():
        return False
    db = _db(store)
    cur = db.current()
    if not cur:
        return False  # a listening orchestrator holds nothing: orphaned executing rows do not count
    return db.get(cur["task"], events=False)["status"] in ("planning", "executing")


def _gate(store=None):
    """One model, one thing: with the flag off, no session or task may start while the worker runs."""
    from . import settings
    if settings.get("orchestrator_resident"):
        return
    if busy(store):
        raise TaskError("hardware occupied: the worker is running a task and parallel execution is off. "
                        "Interrupt it (Stop -> parks -> listens), then try again.")


def submit(text, *, source, workspace="", flow="", model="", session="", gates=None, store=None):
    """Create a task. The same call from MCP, the UI, the CLI or a chat."""
    _gate(store)
    text = (text or "").strip()
    if not text:
        raise TaskError("a task needs a brief: what should be true when it is done?")
    approved = flowlib.load_flows()
    if not flow:
        raise TaskError(f"name the flow; approved: {', '.join(approved)}")
    if flow not in approved:
        raise TaskError(f"'{flow}' is not an approved flow; approved: {', '.join(approved)}")
    cat = modellib.load()
    if not model:
        agents = [m.name for m in cat.models.values() if m.kind == "agent"]
        raise TaskError(f"name the model for this task; approved: {', '.join(agents)}")
    try:
        chosen = cat.get(model)
    except modellib.ModelError as e:
        raise TaskError(str(e))
    if chosen.kind != "agent":
        raise TaskError(f"{model} is a {chosen.kind} model; a task needs an agent model")
    db = _db(store)
    workspace = (workspace or "").strip()
    session = (session or "").strip() or (Path(workspace).name if workspace else "")
    if not workspace:
        # The workspace is optional: a new task in a session reuses where that session has been working, and a
        # brand-new session starts in the folder the person is in.
        workspace = db.latest_workspace(session) or str(Path.cwd())
    return db.submit(text, source, workspace, flow, session, gates, model=model)


def submit_unrouted(text, *, source="cli", workspace="", session="", gates=None, store=None):
    """The one gesture (`ariadne "fix the date test"`): no flow yet, so the worker's router picks one.

    This is the only door that does not name a flow, because the gesture has no room for a picker; an answer outside
    the approved set is still a rejection, never a guess. Every other surface must name the flow and the model.
    """
    text = (text or "").strip()
    if not text:
        raise TaskError("a task needs a brief: what should be true when it is done?")
    return _db(store).submit(text, source, workspace or "", "", session, gates)


def task(tid, events=True, store=None):
    return _db(store).get(tid, events=events)


def tasks(limit=20, store=None):
    """Recent tasks as rows (id, status, flow, source, text, updated)."""
    return _db(store).list(limit)


def wait(tid, timeout=50, store=None):
    return _db(store).wait(tid, timeout=timeout)


def approve(tid, models=None, store=None):
    _db(store).approve(tid, models)
    return _db(store).get(tid)


def revise(tid, feedback, store=None):
    _db(store).revise(tid, feedback)
    return _db(store).get(tid)


def set_gates(tid, gates, store=None):
    _db(store).set_gates(tid, gates)
    return _db(store).get(tid)


def cancel(tid, store=None):
    _db(store).cancel(tid)
    return _db(store).get(tid)


def steer(tid, text, store=None):
    """Give a planning/executing task guidance; the worker delivers it at its next step boundary."""
    return _db(store).steer(tid, text)


def feedback(tid, text, store=None):
    """Notes for a task at any time, kept until a larger model folds them into a shared skill."""
    _db(store).feedback(tid, text)
    return {"id": tid, "next": "recorded; fold it into the flow's skills with save_skill"}


def event(tid, kind, detail="", store=None):
    """Record something that happened to a task (a sign-in, a marker) without changing its status."""
    _db(store).event(tid, kind, detail)


def schedule_create(session, cron, brief="", overrides=None, store=None, now=None):
    """A standing brief for a session. It inherits the flow, model, workspace and gates of the session's most recent
    task - choices the person already made at submit - and creating it is the authorisation for every later run."""
    from . import schedule as sched
    over = dict(overrides or {})
    sched.parse(cron)                                  # refuse a cron nobody can read, before anything is written
    db = _db(store)
    session = (session or "").strip()
    if not session:
        raise TaskError("a schedule needs a session: it is the chain its runs continue")
    mine = [t for t in db.list(200) if (t.get("session") or "") == session]
    if not mine:
        raise TaskError(f"session {session} has no task yet; a schedule inherits its flow, model, workspace and "
                        f"gates from one")
    last = db.get(mine[0]["id"], events=False)
    gates = over["gates"] if over.get("gates") is not None else json.loads(last.get("gates") or "[]")
    return db.schedule_create(session, cron, brief or (last.get("text") or "").splitlines()[0],
                              over.get("flow") or last.get("flow") or "", over.get("model") or last.get("model") or "",
                              over.get("workspace", last.get("workspace") or ""), gates, now=now)


def schedules(store=None):
    return _db(store).schedules()


def schedule_set(name, enabled, store=None):
    return _db(store).schedule_update(name, enabled=1 if enabled else 0)


def schedule_delete(name, store=None):
    _db(store).schedule_delete(name)
    return {"deleted": name}


def define_session(name, *, flow="", model="", workspace="", store=None):
    """Create the workstream without a task: a session is the host, tasks are executions inside it."""
    name = (name or "").strip()
    if not name:
        raise TaskError("a session needs a name: the project or folder it represents")
    _gate(store)
    db = _db(store)
    db.session(name)
    db.session_update(name, flow=flow, model=model, workspace=workspace)
    return sessions_show(name, store=store)


def sessions_show(name, store=None):
    """One workstream: its pivot (flow, model, workspace) and the tasks that belong to it."""
    name = (name or "").strip()
    if not name:
        raise TaskError("name the session")
    for row in sessions_view(limit=500, store=store):
        if row["name"] == name:
            return row
    raise TaskError(f"no session named {name!r}; `ariadne sessions` lists them")


def delete_session(name, store=None):
    """Delete an empty session. A session that hosts tasks is refused with the count."""
    name = (name or "").strip()
    if not name:
        raise TaskError("name the session")
    db = _db(store)
    gone, n = db.session_delete(name)
    if not gone:
        raise TaskError(f"session {name} holds {n} task(s); cancel or move them to delete it")
    return {"deleted": name}


def events_since(since=0.0, limit=200, store=None):
    """Task events after `since`, oldest first: the live feed the UI streams."""
    return _db(store).events_since(since, limit)


def open_feedback(store=None):
    return _db(store).open_feedback()


def resolve_feedback(tids, store=None):
    _db(store).resolve_feedback(tids)


def adopt(tid, reason="No worker was behind this task (crash, kill or reboot).", store=None):
    """Hand a row that is still planning/executing, with no worker behind it, back to the person."""
    db = _db(store)
    t = db.get(tid, events=False)
    if t["status"] in ("planning", "executing") and not worker_running():
        db.update(tid, status="needs_attention",
                  result=f"{reason} The work so far is in the workspace. Approve to continue it, or revise it.")
        db.event(tid, "recover", "adopted by the person (no worker behind it)")
        t = db.get(tid, events=False)
    return t


def inbox(store=None):
    """What needs the person, what is running, what stopped with no worker, what finished."""
    db = _db(store)
    alive = worker_running()
    rows = [db.get(r["id"], events=False) for r in db.list(40)]
    moving = [t for t in rows if t["status"] in ("new", "approved", "planning", "executing")]
    stale = [t for t in moving if t["status"] in ("planning", "executing") and not alive]
    return {"waiting": [t for t in rows if t["status"] in WAITING],
            "running": [t for t in moving if t not in stale],
            "stale": stale,
            "recent": [t for t in rows if t["status"] in FINAL][:8],
            "worker": alive}


def sessions(limit=10, store=None):
    return _db(store).sessions(limit)


def sessions_view(limit=25, store=None):
    """The frontend's unit of work: a session and the tasks that belong to it.

    A session is the durable workstream (normally one repo folder). Tasks live inside it, and a schedule can only be
    created from one - it inherits the session's flow, model, workspace and gates, so a recurring job continues the
    same chain instead of starting cold.
    """
    from . import present
    db = _db(store)
    rows = db.sessions(limit)
    tasks_ = [db.get(r["id"], events=False) for r in db.list(200)]
    out = []
    for s in rows:
        mine = [t for t in tasks_ if (t.get("session") or "") == s["name"]]
        out.append({
            "name": s["name"], "flow": s.get("flow") or "", "model": s.get("model") or "",
            "workspace": s.get("workspace") or "", "segment": s.get("segment"),
            "updated": s.get("updated"), "summary": (s.get("summary") or "")[:200],
            "waiting": sum(1 for t in mine if t["status"] in WAITING),
            "tasks": [{"id": t["id"], "status": t["status"],
                       "label": present.STATUS.get(t["status"], t["status"]),
                       "flow": t.get("flow") or "", "model": t.get("model") or "",
                       "text": (t.get("text") or "").strip().splitlines()[:1]} for t in mine],
        })
    return out


def task_events(tid, after_ts=0.0, store=None):
    """The task's event trail newer than `after_ts`, oldest first - the per-step report a client walks."""
    db = _db(store)
    return [e for e in db.events_since(after_ts, limit=2000) if e.get("task_id") == tid]


def wait_event(tid, after_ts=0.0, timeout=50, store=None):
    """Block until the task logs an event newer than `after_ts`, then return (events, task-cardless).

    The step callback: a client passes the largest ts it has seen each call and walks the task step by step instead
    of one coarse wait for the end.
    """
    import time as _time
    deadline = _time.time() + min(max(timeout, 1), 280)
    while True:
        events = task_events(tid, after_ts, store=store)
        if events or _time.time() >= deadline:
            return events, _db(store).get(tid, events=False)
        _time.sleep(1.0)
