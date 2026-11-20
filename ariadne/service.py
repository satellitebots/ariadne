"""One rulebook. Every surface - MCP, chat, the UI, the CLI - calls these and none of them own a rule.

The rules are the ones the design states: an approved flow, an explicitly chosen agent model, gates before work,
and no surface may accept what another would refuse. Presentation is not here; see `present.py`. The store is
reached only from here (and from the worker, which records progress while a task runs): a surface holds at most a
store handle to pass in, it never calls a store method itself.
"""
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


def submit(text, *, source, workspace="", flow="", model="", session="", gates=None, store=None):
    """Create a task. The same call from MCP, the UI, the CLI or a chat."""
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
    session = (session or "").strip() or (Path(workspace).name if workspace else "")
    return _db(store).submit(text, source, workspace or "", flow, session, gates, model=model)


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


def feedback(tid, text, store=None):
    """Notes for a task at any time, kept until a larger model folds them into a shared skill."""
    _db(store).feedback(tid, text)
    return {"id": tid, "next": "recorded; fold it into the flow's skills with save_skill"}


def event(tid, kind, detail="", store=None):
    """Record something that happened to a task (a sign-in, a marker) without changing its status."""
    _db(store).event(tid, kind, detail)


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
            "name": s["name"], "flow": s.get("flow") or "", "segment": s.get("segment"),
            "updated": s.get("updated"), "summary": (s.get("summary") or "")[:200],
            "waiting": sum(1 for t in mine if t["status"] in WAITING),
            "tasks": [{"id": t["id"], "status": t["status"],
                       "label": present.STATUS.get(t["status"], t["status"]),
                       "flow": t.get("flow") or "", "model": t.get("model") or "",
                       "text": (t.get("text") or "").strip().splitlines()[:1]} for t in mine],
        })
    return out
