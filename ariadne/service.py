"""One rulebook. Every surface - MCP, chat, desktop, CLI - calls these and none of them own a rule.

The rules are the ones the design states: an approved flow, an explicitly chosen agent model, gates before work,
and no surface may accept what another would refuse. Presentation is not here; see `present.py`.
"""
from pathlib import Path

from . import flows as flowlib
from . import models as modellib
from .orchestrator import FINAL, WAITING, Store, TaskError, worker_running
from .paths import STATE

_store = None


def store():
    global _store
    if _store is None:
        _store = Store(STATE / "tasks.db")
    return _store


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


def submit(text, *, source, workspace="", flow="", model="", session="", gates=None):
    """Create a task. The same call from MCP, the desktop, the CLI or a chat."""
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
    return store().submit(text, source, workspace or "", flow, session, gates, model=model)


def task(tid):
    return store().get(tid)


def wait(tid, timeout=50):
    return store().wait(tid, timeout=timeout)


def approve(tid, models=None):
    store().approve(tid, models)
    return store().get(tid)


def revise(tid, feedback):
    store().revise(tid, feedback)
    return store().get(tid)


def set_gates(tid, gates):
    store().set_gates(tid, gates)
    return store().get(tid)


def cancel(tid):
    store().cancel(tid)
    return store().get(tid)


def inbox():
    """What needs the person, what is running, what stopped with no worker, what finished."""
    st = store()
    alive = worker_running()
    rows = [st.get(r["id"], events=False) for r in st.list(40)]
    moving = [t for t in rows if t["status"] in ("new", "approved", "planning", "executing")]
    stale = [t for t in moving if t["status"] in ("planning", "executing") and not alive]
    return {"waiting": [t for t in rows if t["status"] in WAITING],
            "running": [t for t in moving if t not in stale],
            "stale": stale,
            "recent": [t for t in rows if t["status"] in FINAL][:8],
            "worker": alive}


def sessions(limit=10):
    return store().sessions(limit)


def sessions_view(limit=25):
    """The frontend's unit of work: a session and the tasks that belong to it.

    A session is the durable workstream (normally one repo folder). Tasks live inside it, and a schedule can only be
    created from one - it inherits the session's flow, model, workspace and gates, so a recurring job continues the
    same chain instead of starting cold.
    """
    from . import present
    st = store()
    rows = st.sessions(limit)
    tasks = [st.get(r["id"], events=False) for r in st.list(200)]
    out = []
    for s in rows:
        mine = [t for t in tasks if (t.get("session") or "") == s["name"]]
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
