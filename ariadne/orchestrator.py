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
  status TEXT, plan TEXT DEFAULT '', feedback TEXT DEFAULT '', result TEXT DEFAULT '', error TEXT DEFAULT '',
  models TEXT DEFAULT '', session TEXT DEFAULT '');
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
            have = [r["name"] for r in c.execute("PRAGMA table_info(tasks)")]
            for col in ("models", "session"):
                if col not in have:
                    c.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT DEFAULT ''")

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

    def submit(self, text, source="cli", workspace="", flow="", session=""):
        """session: a Hermes session to continue (the caller's conversation); default: one session per task."""
        text = (text or "").strip()
        if not text:
            raise TaskError("the task text is empty")
        tid = time.strftime("t%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        now = time.time()
        with self._conn() as c:
            c.execute("INSERT INTO tasks(id, created, updated, source, text, workspace, flow, status, session) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (tid, now, now, source, text, workspace or "", flow or "", "new",
                                                     (session or "").strip() or tid))
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

    def approve(self, tid, models=None):
        """Sign-off. models: {step number or 'all': model name} to change the plan's choices first. Approval locks
        the model plan: execution uses exactly these models, and fetches any that are not installed.
        Also re-approves a task that stopped for attention (a model failed to install, a tool was missing)."""
        t = self.get(tid, events=False)
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


def hermes_run(flow, phase, prompt, workspace, tid, model=None, session=None):
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
    if model:
        cmd += ["-m", model]
    if session:  # Hermes's own sessions (state.db in the flow's home): plan, revisions and execute share one
        cmd += ["--continue", session, "--create-if-missing", "--no-restore-cwd"]
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

MODELS you may assign to steps (one per step; {default_model} if a step does not need anything else):
{models}
Agent models do a step themselves. A generate model drafts text for a step (the agent asks it through
generate_text); an image model renders images (generate_image). Pick the best model for each step, not the biggest.

Investigate just enough to plan well (look at the relevant files). Then reply with a backbrief in exactly this form:

MISSION: <one sentence: what will be true when this is done>
FLOW: {flow}
STEPS:
1. <step> - tools: <tools it uses> - model: <model name from MODELS>
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

# ---------- model plan: a model per step, suggested by the planner, locked at sign-off ----------

STEP_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
MODEL_RE = re.compile(r"\bmodel:\s*`?([A-Za-z0-9][\w.\-]*)", re.I)
SECTION_RE = re.compile(r"^[A-Z][A-Z ]+:")


def parse_model_plan(plan_text, flow, catalog):
    """The backbrief's steps and the model each names; a missing or unknown name gets the flow's agent model."""
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
            notes.append(f"step {m.group(1)} named '{name}', which is not in the catalog; using {flow.model}")
            name = ""
        steps.append({"n": int(m.group(1)), "text": body, "model": name or flow.model})
    return {"steps": steps, "agent": flow.model, "notes": notes}


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
    if gaps:
        out.append("MISSING TOOLS (execution will not start until they are there): " + "; ".join(gaps))
    out.append("Change a model: approve with --model STEP=NAME (or all=NAME), or revise. Models: python -m ariadne models")
    return "\n".join(out)


def missing_tools(mp, flow, catalog):
    gaps = [f"{m} (python -m ariadne install --system)" for m in flowlib.missing_requirements(flow)]
    gaps += [f"MCP server '{s}' (add it to mcp_servers in flows/{flow.name}/flow.yaml)"
             for s in needed_servers(mp, catalog) if s not in flow.mcp_servers]
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


ROUTE_PROMPT = """Pick the flow for this task. Flows:
{flows}

Task: {text}

Reply with only the flow name."""


# ---------- the worker ----------

class Worker:
    def __init__(self, store=None, memory=None, flows=None, runner=hermes_run, router_model="router", llm_chat=None,
                 catalog=None, installer=None, on_installed=None, kv=None):
        from .kvcache import KVCache, NoKVCache
        self.kv = kv or (KVCache() if runner is hermes_run else NoKVCache())
        from . import models as modellib
        self.catalog = catalog or modellib.load()
        self.installer = installer or modellib.install
        self.on_installed = on_installed or _reload_models
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
        missing = flowlib.missing_requirements(flow)
        if missing:
            msg = (f"flow '{name}' needs {', '.join(missing)}, which this machine does not have. "
                   "Install them (python -m ariadne install --system), then revise the task to retry.")
            self.store.update(t["id"], flow=name, status="needs_attention", result=msg)
            self.store.event(t["id"], "route", f"{name}: missing {', '.join(missing)}")
            return
        self.store.update(t["id"], flow=name)
        self.store.event(t["id"], "route", f"{name} ({why})")
        planner = self.catalog.get(flow.model)
        if not planner.installed():
            msg = (f"flow '{name}' plans and works with {flow.model}, which is not installed ({planner.size_gb:g} GB). "
                   f"Install it (python -m ariadne models install {flow.model}), then revise the task to retry.")
            self.store.update(t["id"], status="needs_attention", result=msg)
            self.store.event(t["id"], "route", f"{flow.model} not installed")
            return
        ws = self.workspace(t)
        hits = self.memory.recall(f"{t['text']} {ws}", limit=5)
        feedback = f"\nFEEDBACK ON THE LAST PLAN (address it):\n{t['feedback']}\n" if t["feedback"] else ""
        prompt = PLAN_PROMPT.format(flow=name, source=t["source"], text=t["text"], workspace=ws,
                                    feedback=feedback, memory=format_hits(hits),
                                    exec_tools=", ".join(flow.execute_toolsets + [f"{m} (MCP)" for m in flow.mcp_servers]),
                                    models=self.catalog.text(), default_model=flow.model)
        self.store.event(t["id"], "plan", f"started ({len(hits)} memories recalled)")
        r = self.run(flow, "plan", prompt, ws, t, flow.model)
        if r.exit_code != 0 or not r.text:
            self.store.update(t["id"], status="failed", error=f"plan run failed (exit {r.exit_code}); log {r.log}")
            self.store.event(t["id"], "plan", f"failed, log {r.log}")
            return
        mp = parse_model_plan(r.text, flow, self.catalog)
        self.store.update(t["id"], status="awaiting_signoff", plan=r.text.rstrip() + "\n" + model_block(mp, flow, self.catalog),
                          models=json.dumps(mp))
        self.store.event(t["id"], "backbrief", "ready for sign-off")
        self.memory.record("task", t["id"], f"{t['text']}\nstatus: awaiting sign-off",
                           [("uses_flow", "flow", name), ("in_workspace", "workspace", ws)])

    def run(self, flow, phase, prompt, ws, t, model):
        """One Hermes run in the task's session on `model`, with that session's KV cache woken first and parked after."""
        session = t.get("session") or t["id"]
        note = self.kv.restore(session, model)
        if note:
            self.store.event(t["id"], "kv", f"{model}: {note}")
        r = self.runner(flow, phase, prompt, ws, t["id"], model=model, session=session)
        note = self.kv.save(session, model)
        if note:
            self.store.event(t["id"], "kv", f"{model}: {note}")
        return r

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

    def prepare(self, t, flow, mp):
        """Before step 1: every tool the plan needs is there and every locked model is installed (fetched now if
        not; the sign-off covered it). Returns what stops the task, or ''."""
        gaps = missing_tools(mp, flow, self.catalog)
        if gaps:
            return "Execution did not start; missing: " + "; ".join(gaps) + ". Fix that, then approve again."
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

    def execute(self, t):
        flow = self.flows.get(t["flow"])
        if not flow:
            self.store.update(t["id"], status="failed", error=f"flow '{t['flow']}' no longer exists")
            return
        mp = json.loads(t["models"]) if t.get("models") else {"steps": [], "agent": flow.model, "notes": []}
        problem = self.prepare(t, flow, mp)
        if problem:
            self.store.update(t["id"], status="needs_attention", result=problem)
            self.store.event(t["id"], "prepare", problem[:300])
            return
        ws = self.workspace(t)
        groups, reports = step_groups(mp, self.catalog), []
        for i, (agent, steps) in enumerate(groups):
            scope, extra, attempts, last = step_scope(steps, groups, mp, self.catalog), "", 0, i == len(groups) - 1
            label = f"steps {', '.join(str(s['n']) for s in steps)}" if len(groups) > 1 else "plan"
            while True:
                attempts += 1
                self.store.event(t["id"], "execute", f"{label} on {agent}, attempt {attempts}")
                r = self.run(flow, "execute", EXEC_PROMPT.format(flow=flow.name, text=t["text"], workspace=ws,
                                                                  plan=t["plan"], extra=scope + extra), ws, t, agent)
                if r.exit_code != 0 or not r.text:
                    return self._finish(t, flow, ws, "failed", "\n\n".join(reports + [r.text]),
                                        f"execute run failed (exit {r.exit_code}); log {r.log}")
                if r.text.lstrip().upper().startswith("OFF-PLAN"):
                    self.store.update(t["id"], status="needs_attention", result=r.text)
                    self.store.event(t["id"], "execute", "stopped: off-plan, back to the person for a new sign-off")
                    return
                if not last:
                    reports.append(r.text)
                    break
                failures = self.run_checks(flow, ws)
                if not failures:
                    self.store.event(t["id"], "checks", "passed" if flow.checks else "none defined")
                    return self._finish(t, flow, ws, "done", "\n\n".join(reports + [r.text]))
                self.store.event(t["id"], "checks", f"failed: {failures[0][:300]}")
                if attempts >= 2:
                    return self._finish(t, flow, ws, "failed", "\n\n".join(reports + [r.text]),
                                        "checks still failing:\n" + "\n".join(failures))
                extra = ("\nA PREVIOUS ATTEMPT FINISHED BUT THESE CHECKS FAILED. Fix them, staying on the plan:\n"
                         + "\n".join(failures) + "\n")

    def _finish(self, t, flow, ws, status, result, error=""):
        self.store.update(t["id"], status=status, result=result or "", error=error)
        if (t.get("session") or t["id"]) == t["id"]:  # the task's own session ends with it; a caller's lives on
            self.kv.drop(t["id"])
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
    subprocess.run([str(paths.HERMES_EXE), "gateway", "stop"], env=dict(os.environ, HERMES_HOME=str(home)),
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=120)


def serve(idle_exit=1800):
    from .deps import require
    require()
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
    s.add_argument("--session", default="", help="continue this Hermes session (default: a new one for the task)")
    g = sub.add_parser("get"); g.add_argument("id")
    w = sub.add_parser("wait"); w.add_argument("id"); w.add_argument("--timeout", type=int, default=600)
    a = sub.add_parser("approve"); a.add_argument("id")
    a.add_argument("--model", action="append", default=[], metavar="STEP=NAME",
                   help="change a step's model before locking the plan (STEP may be 'all'); repeatable")
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
        tid = st.submit(text, "cli", args.workspace, args.flow, args.session)
        ensure_worker()
        _print(st.wait(tid, args.wait) if args.wait else {"id": tid, "status": "new"})
    elif args.cmd == "get":
        _print(st.get(args.id))
    elif args.cmd == "wait":
        ensure_worker()
        _print(st.wait(args.id, args.timeout))
    elif args.cmd == "approve":
        st.approve(args.id, ",".join(args.model) or None); ensure_worker(); _print(st.get(args.id, events=False))
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
