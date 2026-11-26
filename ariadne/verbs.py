"""The one contract: every verb a front may call (docs/DESIGN.md, "Fronts: one contract").

MCP, the HTTP API behind the UI, and the chat are generated from `VERBS`; none of them defines a verb of its own.
A verb is a plain function taking keyword arguments and returning JSON-able data. `mcp_only` marks the bypass and
the extra control an outside agent gets; everything else exists on all three fronts.
"""
import inspect
import json
import time
from dataclasses import dataclass, field

from . import durable, park, permissions, spec as speclib


@dataclass
class Verb:
    name: str
    fn: callable
    group: str
    doc: str
    mcp_only: bool = False
    params: dict = field(default_factory=dict)   # name -> (annotation, default or inspect._empty)


VERBS: dict = {}


def verb(group, mcp_only=False):
    def wrap(fn):
        sig = inspect.signature(fn)
        params = {n: (p.annotation, p.default) for n, p in sig.parameters.items()}
        VERBS[fn.__name__] = Verb(fn.__name__, fn, group, inspect.getdoc(fn) or "", mcp_only, params)
        return fn
    return wrap


class VerbError(ValueError):
    """A request a person can fix: say what is wrong, never a traceback."""


class Ctx:
    """What the verbs work against. Tests replace any of it."""
    def __init__(self, store=None, flows=None, catalog=None, broker=None, orchestrator=None):
        self._store, self._flows, self._catalog, self._broker, self.orchestrator = store, flows, catalog, broker, orchestrator

    @property
    def store(self):
        if self._store is None:
            self._store = durable.Store()
        return self._store

    @property
    def flows(self):
        if self._flows is None:
            from . import flows
            self._flows = flows.load_flows()
        return self._flows

    @property
    def catalog(self):
        if self._catalog is None:
            from . import models
            self._catalog = models.load()
        return self._catalog

    @property
    def broker(self):
        if self._broker is None:
            from . import broker
            self._broker = broker.default()
        return self._broker


ctx = Ctx()


def call(name, **args):
    """Run a verb by name (what every front does). Unknown arguments are an error, not silently dropped."""
    v = VERBS.get(name)
    if not v:
        raise VerbError(f"no verb '{name}'; verbs: {', '.join(VERBS)}")
    unknown = set(args) - set(v.params)
    if unknown:
        raise VerbError(f"{name}: unknown argument(s) {', '.join(sorted(unknown))}; takes {', '.join(v.params)}")
    return v.fn(**args)


# ---------- shapes the fronts render ----------

def _task_view(t):
    s = ctx.store
    sp = s.spec(t["id"]) or {}
    return {"id": t["id"], "name": t["name"], "flow": t["flow"], "status": t["status"], "version": t["version"],
            "goal": sp.get("goal", ""), "trigger": speclib.describe_trigger(sp), "scheduled": bool(t["scheduled"]),
            "next_due": t["next_due"], "last_run": t["last_run"], "updated": t["updated"]}


def _run_view(r, detail=False):
    s = ctx.store
    t = s.task(r["task_id"]) or {}
    sp = s.spec(r["task_id"], r["version"]) or {}
    v = {"id": r["id"], "task": t.get("name", r["task_id"]), "task_id": r["task_id"], "version": r["version"],
         "status": r["status"], "trigger": r["trigger"], "step": r["step"], "steps_total": len(sp.get("steps", [])),
         "created": r["created"], "started": r["started"], "ended": r["ended"], "error": r["error"]}
    q = permissions.pending(r["id"]) if r["status"] in durable.LIVE else None
    v["ask"] = {**q, "text": permissions.describe(q)} if q else None
    if detail:
        steps = s.steps(r["id"])
        v["steps"] = [{"n": st["n"], "title": st["title"], "model": st["model"],
                       "attempts": [{k: a[k] for k in ("attempt", "status", "started", "ended", "report", "gate")}
                                    for a in steps if a["n"] == st["n"]]} for st in sp.get("steps", [])]
        v["result"] = r["result"]
        v["events"] = s.events(r["id"], limit=300, newest=True)
        act = next((e for e in reversed(v["events"]) if e["kind"] in ACTIVITY), None)
        v["activity"] = {"ts": act["ts"], "kind": act["kind"], "detail": act["detail"]} if act else None
        v["workspace"] = r["workspace"]
        v["notes"] = s.steers(r["id"])
        from . import jobs as jobslib
        v["jobs"] = [_job_view(j) for j in jobslib.recent(20, task_id=r["id"])]
    return v


def _job_view(j):
    res = json.loads(j.get("result") or "{}") if j.get("result") else {}
    return {"id": j["id"], "run": j["task_id"], "status": j["status"], "command": j["command"], "why": j["why"],
            "created": j["created"], "started": j["started"], "ended": j["ended"], "exit_code": j["exit_code"],
            "seconds": res.get("seconds"), "log_tail": (res.get("log_tail") or "")[-1200:]}


def _draft_view(d):
    problems = []
    try:
        speclib.validate(d["spec"], ctx.flows, ctx.catalog)
    except speclib.SpecError as e:
        problems = e.problems
    return {"id": d["id"], "status": d["status"], "flow": d["flow"], "task_id": d["task_id"],
            "base_version": d["base_version"], "spec": d["spec"], "yaml": speclib.dump(d["spec"]),
            "asks": d["asks"], "problems": problems, "ready": not problems,
            "messages": ctx.store.messages(d["id"]), "updated": d["updated"]}


def _need(obj, what, ref):
    if not obj:
        raise VerbError(f"no {what} '{ref}'")
    return obj


def _task(ref):
    return _need(ctx.store.find_task(ref), "task", ref)


def _run(ref):
    return _need(ctx.store.run(ref), "run", ref)


def _draft(ref, open_only=True):
    d = _need(ctx.store.draft(ref), "draft", ref)
    if open_only and d["status"] != "open":
        raise VerbError(f"draft {ref} is {d['status']}")
    return d


# ---------- Define ----------

@verb("define")
def draft(text: str = "", flow: str = "", name: str = "", workspace: str = "") -> dict:
    """Open a draft task from a flow's template. `text` is what you want, in your words; the orchestrator turns it
    into the definition with `say`."""
    if not flow:
        if len(ctx.flows) == 1:
            flow = next(iter(ctx.flows))
        else:
            raise VerbError(f"say which flow: {', '.join(ctx.flows)}")
    fl = ctx.flows.get(flow)
    if not fl:
        raise VerbError(f"no flow '{flow}'; flows: {', '.join(ctx.flows)}")
    sp, asks = speclib.from_template(fl, name=name, workspace=workspace)
    if text and asks:            # what you typed answers the template's first question
        sp["params"][next(iter(asks))] = text
    elif text and not sp.get("goal"):
        sp["goal"] = text
    did = ctx.store.draft_new(flow, sp, asks, source="front")
    if text:
        ctx.store.message(did, "person", text)
    return _draft_view(ctx.store.draft(did))


@verb("define")
def say(draft: str, message: str) -> dict:
    """One turn with the orchestrator about a draft: it asks what is missing and updates the definition. Waits for
    the machine if a run holds it (the answer says so)."""
    d = _draft(draft)
    if ctx.orchestrator is None:
        from . import orchestrate
        ctx.orchestrator = orchestrate.Orchestrator()
    ctx.store.message(d["id"], "person", message)
    reply = ctx.orchestrator.turn(d["id"], message, store=ctx.store, flows=ctx.flows, catalog=ctx.catalog,
                                  broker=ctx.broker)
    ctx.store.message(d["id"], "orchestrator", reply)
    return {"reply": reply, **_draft_view(ctx.store.draft(d["id"]))}


@verb("define")
def draft_show(draft: str) -> dict:
    """A draft: its definition (as YAML), what is still missing, and the conversation so far."""
    return _draft_view(_draft(draft, open_only=False))


@verb("define")
def draft_fill(draft: str, name: str = "", workspace: str = "", trigger: str = "", params: dict = None) -> dict:
    """Fill in a draft directly, without the orchestrator: its name, workspace folder, when it runs ('manual',
    'now', an ISO time or cron) and answers to the template's questions. Empty values leave a field as it is."""
    d = _draft(draft)
    sp = dict(d["spec"])
    if name.strip():
        sp["name"] = name.strip()
    if workspace.strip():
        sp["workspace"] = workspace.strip()
    trig = trigger.strip()
    if trig:
        sp["trigger"] = ({"kind": trig} if trig in ("manual", "now") else
                         {"kind": "cron", "cron": trig} if len(trig.split()) == 5 else {"kind": "at", "at": trig})
    if params:
        sp["params"] = {**(sp.get("params") or {}), **{k: str(v) for k, v in params.items() if str(v).strip()}}
    ctx.store.draft_set(d["id"], sp)
    ctx.store.event(d["id"], "draft", "filled in from the form")
    return _draft_view(ctx.store.draft(d["id"]))


@verb("define")
def draft_update(draft: str, yaml: str) -> dict:
    """Replace a draft's definition with this YAML. Problems are listed, not refused: a draft may be incomplete."""
    d = _draft(draft)
    try:
        sp = speclib.load(yaml)
    except Exception as e:
        raise VerbError(f"that is not YAML: {e}")
    ctx.store.draft_set(d["id"], sp)
    ctx.store.event(d["id"], "draft", "definition updated")
    return _draft_view(ctx.store.draft(d["id"]))


@verb("define")
def drafts() -> list:
    """Open drafts."""
    return [_draft_view(d) for d in ctx.store.drafts()]


@verb("define")
def sign(draft: str) -> dict:
    """Sign a draft: it becomes the next version of its task (or a new task) and is scheduled by its trigger.
    Only a draft with no problems can be signed."""
    d = _draft(draft)
    try:
        sp = speclib.validate(d["spec"], ctx.flows, ctx.catalog)
    except speclib.SpecError as e:
        raise VerbError("not ready to sign: " + "; ".join(e.problems))
    other = ctx.store.task_by_name(sp["name"])
    if other and other["id"] != d["task_id"]:
        raise VerbError(f"a task named '{sp['name']}' already exists; edit it, or choose another name")
    tid, v = ctx.store.sign(sp, d["task_id"])
    ctx.store.draft_close(d["id"], "signed")
    if sp["trigger"]["kind"] == "now":
        rid = ctx.store.run_new(tid, "signed: run now")
        return {**_task_view(ctx.store.task(tid)), "run": rid}
    return _task_view(ctx.store.task(tid))


@verb("define")
def edit(task: str) -> dict:
    """Open a draft from a task's current version; signing it makes the next version."""
    t = _task(task)
    sp = ctx.store.spec(t["id"])
    fl = ctx.flows.get(t["flow"])
    asks = (speclib.template(fl) or {}).get("params", {}) if fl else {}
    did = ctx.store.draft_new(t["flow"], sp, asks, task_id=t["id"], base_version=t["version"], source="edit")
    return _draft_view(ctx.store.draft(did))


@verb("define")
def drop(draft: str) -> dict:
    """Throw a draft away."""
    d = _draft(draft)
    ctx.store.draft_close(d["id"], "dropped")
    return {"id": d["id"], "status": "dropped"}


@verb("define", mcp_only=True)
def define(yaml: str) -> dict:
    """The bypass: hand in a full task definition (YAML, see `flows`). It becomes a draft to check and sign, so the
    local orchestrator never loads."""
    try:
        sp = speclib.load(yaml)
    except Exception as e:
        raise VerbError(f"that is not YAML: {e}")
    fl = ctx.flows.get(sp.get("flow") or "")
    if not fl:
        raise VerbError(f"flow: one of {', '.join(ctx.flows)}")
    did = ctx.store.draft_new(fl.name, sp, (speclib.template(fl) or {}).get("params", {}), source="mcp")
    return _draft_view(ctx.store.draft(did))


@verb("define")
def flows() -> list:
    """The flows (task templates): what each is for, the parameters it asks for, its steps and the tools allowed."""
    out = []
    for fl in ctx.flows.values():
        tpl = speclib.template(fl) or {}
        out.append({"name": fl.name, "description": fl.description, "when": fl.when, "model": fl.step_model,
                    "params": tpl.get("params", {}), "steps": [s.get("title") for s in tpl.get("steps", [])],
                    "tools": speclib.tools_for(fl)})
    return out


# ---------- Tasks ----------

@verb("tasks")
def tasks() -> list:
    """Signed tasks: what each does, its trigger, and its last run."""
    return [_task_view(t) for t in ctx.store.tasks()]


@verb("tasks")
def task(task: str) -> dict:
    """A task: its current definition and its recent runs."""
    t = _task(task)
    sp = ctx.store.spec(t["id"])
    runs = [_run_view(r) for r in ctx.store.runs(t["id"], limit=20)]
    ended = [r for r in runs if r["status"] not in durable.LIVE]
    took = [r["ended"] - r["started"] for r in ended if r["status"] == "done" and r["ended"] and r["started"]]
    stats = {"runs": len(ended), "done": sum(r["status"] == "done" for r in ended),
             "needs_you": sum(r["status"] == "needs_you" for r in ended),
             "failed": sum(r["status"] in ("failed", "timed_out") for r in ended),
             "cancelled": sum(r["status"] == "cancelled" for r in ended),
             "typical_s": sorted(took)[len(took) // 2] if took else None}
    return {**_task_view(t), "yaml": speclib.dump(sp), "spec": sp, "stats": stats, "runs": runs}


@verb("tasks")
def schedule(task: str, trigger: str, tz: str = "") -> dict:
    """Set when a task runs: 'manual', 'now', an ISO time ('2026-11-25T07:00'), or cron ('0 7 * * 1-5').
    It is signed as the next version (you asked for exactly this change)."""
    t = _task(task)
    sp = dict(ctx.store.spec(t["id"]))
    trig = trigger.strip()
    if trig in ("manual", "now"):
        sp["trigger"] = {"kind": trig}
    elif len(trig.split()) == 5:
        sp["trigger"] = {"kind": "cron", "cron": trig}
    else:
        sp["trigger"] = {"kind": "at", "at": trig}
    if tz:
        sp["tz"] = tz
    try:
        sp = speclib.validate(sp, ctx.flows, ctx.catalog)
    except speclib.SpecError as e:
        raise VerbError("; ".join(e.problems))
    ctx.store.sign(sp, t["id"])
    ctx.store.task_set(t["id"], scheduled=1)
    if sp["trigger"]["kind"] == "now":
        ctx.store.run_new(t["id"], "scheduled: now")
    return _task_view(ctx.store.task(t["id"]))


@verb("tasks")
def unschedule(task: str) -> dict:
    """Stop a task's trigger; it still runs when you start it."""
    t = _task(task)
    ctx.store.task_set(t["id"], scheduled=0)
    ctx.store.event(t["id"], "schedule", "off")
    return _task_view(ctx.store.task(t["id"]))


@verb("tasks")
def retire(task: str) -> dict:
    """Retire a task: no more runs; its history stays."""
    t = _task(task)
    ctx.store.task_set(t["id"], status="retired", scheduled=0)
    return _task_view(ctx.store.task(t["id"]))


# ---------- Runs ----------

@verb("runs")
def run(task: str) -> dict:
    """Run a task now (its current version). It queues for the machine like everything else."""
    t = _task(task)
    if t["status"] != "signed":
        raise VerbError(f"task {t['name']} is {t['status']}")
    return _run_view(ctx.store.run(ctx.store.run_new(t["id"], "manual")))


@verb("machine")
def jobs(run: str = "", limit: int = 30) -> list:
    """Heavy work runs as jobs with the models unloaded: the newest, or one run's. Status, command, why, exit code,
    seconds and the end of the log."""
    from . import jobs as jobslib
    rid = _run(run)["id"] if run else None
    return [_job_view(j) for j in jobslib.recent(limit, task_id=rid)]


@verb("machine")
def activity(limit: int = 60) -> list:
    """What happened lately across every run and conversation, newest first: steps, tool calls, model calls, jobs,
    parks, asks, steering notes and ends."""
    rows = ctx.store.events(limit=max(1, min(int(limit), 500)), newest=True)
    return [{"ts": e["ts"], "ref": e["ref"], "kind": e["kind"], "detail": e["detail"]} for e in reversed(rows)]


@verb("machine")
def rules() -> dict:
    """What workers may do (permissions.yaml: default allow; what asks, what is refused) and what local workers get
    wrong, with the rule that removes each (docs/WORKER-RECIPE.md)."""
    try:
        perms = permissions.load()
    except ValueError as e:
        perms = {"error": str(e)}
    recipe = []
    from . import paths as _paths
    doc = _paths.ROOT / "docs" / "WORKER-RECIPE.md"
    if doc.exists():
        for line in doc.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("| W") and len(cells) >= 5:
                recipe.append({"id": cells[0], "failure": cells[1], "seen": cells[2], "rule": cells[3], "where": cells[4]})
    return {"permissions": perms, "permissions_file": str(permissions.FILE), "recipe": recipe}


@verb("runs")
def runs(task: str = "", live: bool = False, limit: int = 50) -> list:
    """Runs, newest first: all, one task's, or only the live ones."""
    tid = _task(task)["id"] if task else None
    return [_run_view(r) for r in ctx.store.runs(tid, live=live, limit=max(1, min(int(limit), 500)))]


@verb("runs")
def run_show(run: str) -> dict:
    """A run: each step's attempts, reports and gate verdicts, and its events."""
    return _run_view(_run(run), detail=True)


ACTIVITY = ("tool", "model", "job")     # events that show a run is doing work (engine.Progress, jobs.run)


@verb("runs")
def progress(run: str, recent: int = 15) -> dict:
    """Is a run making progress? Its status and step, seconds since its last tool call, model call or job output,
    how many of each, the files it wrote or edited, and its most recent activity. Nothing stops a run on its own:
    read this before cancelling one that looks stuck."""
    r = _run(run)
    ev = ctx.store.events(r["id"], limit=2000, newest=True)
    act = [e for e in ev if e["kind"] in ACTIVITY]
    last = act[-1] if act else None
    changed = sorted({e["detail"].split(": ", 1)[-1].split(" ", 1)[-1] for e in act if e["kind"] == "tool"
                      and e["detail"].split(": ", 1)[-1].startswith(("wrote ", "edited "))})
    quiet = next((e for e in reversed(ev) if e["kind"] == "quiet"), None)
    loop = next((e for e in reversed(ev) if e["kind"] == "looping"), None)
    work = next((e for e in reversed(act) if e["kind"] == "tool" and e["detail"].split(": ", 1)[-1].startswith(
        ("wrote ", "edited ", "submitted a job"))), None)
    view = _run_view(r)
    return {"run": r["id"], "task": view["task"], "status": r["status"], "step": r["step"],
            "steps_total": view["steps_total"], "ask": view["ask"],
            "seconds_since_activity": round(time.time() - last["ts"]) if last else None,
            "last_activity": last["detail"] if last else "",
            "tool_calls": sum(e["kind"] == "tool" for e in act), "model_calls": sum(e["kind"] == "model" for e in act),
            "files_changed": changed, "quiet_note": quiet["detail"] if quiet and (not last or quiet["ts"] > last["ts"])
            else "", "looping_note": loop["detail"] if loop and (not work or loop["ts"] > work["ts"]) else "",
            "recent": [{"ts": e["ts"], "kind": e["kind"], "detail": e["detail"]} for e in act[-recent:]],
            "machine": ctx.broker.describe()}


@verb("runs")
def park_run(run: str) -> dict:
    """Park a running run: it stops at its next step boundary, saves its cache and gives the machine back. Nothing
    else ever stops a run on its own. Talk to the orchestrator, `steer` it, then `resume`."""
    r = _run(run)
    if r["status"] not in ("running", "waiting"):
        raise VerbError(f"run {run} is {r['status']}; only a running run can be parked")
    park.request(by=f"run {r['id']}")
    ctx.store.event(r["id"], "park", "requested; it stops at the next step boundary")
    return _run_view(ctx.store.run(r["id"]))


@verb("runs")
def steer(run: str, text: str) -> dict:
    """Leave a note for a run's next step (delivered at the step boundary). Usually: park, discuss, steer, resume."""
    r = _run(run)
    if r["status"] not in durable.LIVE:
        raise VerbError(f"run {run} is {r['status']}; steering is for a live run")
    ctx.store.steer(r["id"], text)
    return _run_view(ctx.store.run(r["id"]))


@verb("runs")
def resume(run: str) -> dict:
    """Resume a parked run: it waits for the machine, wakes its cache and continues with any steering notes."""
    r = _run(run)
    park.resume()
    ctx.store.event(r["id"], "park", "resume requested")
    return _run_view(ctx.store.run(r["id"]))


@verb("runs")
def approve(run: str) -> dict:
    """Say yes to what a run is asking (permissions.yaml ask). The yes holds for the rest of the run."""
    r = _run(run)
    q = permissions.answer(r["id"], yes=True)
    if not q:
        raise VerbError(f"run {run} is not asking anything")
    ctx.store.steer(r["id"], f"The person approved: {q['what']}. Go ahead and do it now.")
    ctx.store.event(r["id"], "ask", f"approved: {q['what'][:300]}")
    return _run_view(ctx.store.run(r["id"]))


@verb("runs")
def reject(run: str, why: str = "") -> dict:
    """Say no to what a run is asking. The worker is told no (and why) and continues another way."""
    r = _run(run)
    q = permissions.answer(r["id"], yes=False)
    if not q:
        raise VerbError(f"run {run} is not asking anything")
    ctx.store.steer(r["id"], f"The person said no to: {q['what']}." + (f" Why: {why}" if why else "")
                    + " Do not try it again; do the work another way, or report that it cannot be done.")
    ctx.store.event(r["id"], "ask", f"rejected: {q['what'][:300]}" + (f" ({why})" if why else ""))
    return _run_view(ctx.store.run(r["id"]))


@verb("runs")
def cancel(run: str) -> dict:
    """Cancel a run. A queued run ends now; a running one stops at its next step boundary."""
    r = _run(run)
    if r["status"] == "queued":
        ctx.store.run_set(r["id"], status="cancelled", ended=time.time())
    elif r["status"] in durable.LIVE:
        ctx.store.run_set(r["id"], error="cancel requested")
        if r["status"] == "parked":
            park.resume()
        permissions.answer(r["id"], yes=False)
    ctx.store.event(r["id"], "cancel", "requested")
    return _run_view(ctx.store.run(r["id"]))


@verb("runs")
def rerun(run: str) -> dict:
    """Run the same task again (its current version)."""
    r = _run(run)
    return _run_view(ctx.store.run(ctx.store.run_new(r["task_id"], f"rerun of {r['id']}")))


# ---------- Machine ----------

@verb("machine")
def machine() -> dict:
    """Who holds the machine, who is waiting, and a one-line summary."""
    b = ctx.broker
    return {**b.status(), "summary": b.describe()}


@verb("machine", mcp_only=True)
def run_logs(run: str, step: int = 0) -> dict:
    """The full logs of a run's steps (or one step): paths and the last 200 lines of each."""
    r = _run(run)
    out = []
    for st in ctx.store.steps(r["id"]):
        if step and st["n"] != step:
            continue
        text = ""
        try:
            from pathlib import Path
            text = "\n".join(Path(st["log"]).read_text(encoding="utf-8", errors="replace").splitlines()[-200:])
        except Exception:
            pass
        out.append({"n": st["n"], "attempt": st["attempt"], "log": st["log"], "tail": text})
    return {"run": r["id"], "steps": out}


@verb("machine", mcp_only=True)
def events(since: float = 0.0) -> list:
    """Raw events across everything, after `since` (epoch seconds)."""
    return ctx.store.events(since=since)


def schema(v: Verb) -> dict:
    """A JSON schema for a verb's arguments (MCP tool input, chat tool parameters)."""
    kinds = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object", list: "array"}
    props, req = {}, []
    for n, (ann, default) in v.params.items():
        props[n] = {"type": kinds.get(ann, "string")}
        if default is inspect.Parameter.empty:
            req.append(n)
    return {"type": "object", "properties": props, "required": req}


def dumps(x):
    return json.dumps(x, ensure_ascii=False, indent=1, default=str)


from . import orchestrate  # noqa: E402,F401  -- registers `chat`, the orchestrator's general conversation
