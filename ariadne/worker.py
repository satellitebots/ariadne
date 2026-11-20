"""The worker: one Hermes session per task, gates at the edge, and the resume that keeps its context.

The task is planned read-only, signed off by a person, then executed. Execution is **one Hermes session per task**
carrying the rendered plan; steps are guidance inside that context, not processes. When the plan assigns a step to a
different agent model, that is an explicit chain of sessions recorded in the plan (`models.chain`), and each link
gets a carry-forward note - no hidden spawn per step, no reload per step.

A failed gate resumes *the same* session with the failure (`hermes chat -r`); it does not start a fresh one from a
summary. Out of time or turns is not failure: what was written stays and the gates decide.

Everything here is model-free to test: `Worker` takes an injected runner, a clock and a catalog, and a test passes a
fake for each. This module owns no rules about who may do what - that is `service.py` - and no formatting - that is
`present.py` and `render.py`.
"""
import json
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import flows as flowlib
from . import jobs, llm, park, paths, protocol, render
from .errors import TaskError
from .memory import Memory, format_hits
from .store import Store, gates_text

# ---------- running Hermes ----------

@dataclass
class RunResult:
    text: str
    exit_code: int
    log: str
    session_id: str = ""     # the Hermes session the run used (printed by -Q)


def runtime_run(flow, phase, prompt, workspace, tid, model=None, session=None):
    """One run in Ariadne's own runtime: a prompt in, a report out, and a session id to resume.

    `session` is the runtime's session name, so a failed gate resumes the same conversation. Out of time comes back as
    124 and out of turns as 126 - neither is failure: the worker keeps what was written and lets the gates decide. The
    flow's MCP servers
    ride along as `mcp__` tools; a server that will not start is said so in the report, not hidden. The flow's shared
    skills ride along as `skills_list`/`skill_view`, so a run can read a skill body, not just its plan-prompt line.
    `web_search` rides along too (the plan prompt already assumes it): DDGS behind an injectable transport, and
    nothing to close.

    Before the run it writes the markers the flow's servers read, into `flow.home`: `ariadne_phase` ("plan" for the
    read-only side phases, else the phase), `ariadne_task` and `ariadne_workspace`. The markers are the contract with
    the flow's MCP servers: `jobs_mcp` reads `ariadne_task` and `ariadne_workspace` from `ARIADNE_FLOW_HOME`, so
    without them `submit_job` would record a job with no task. KV needs no code here: `Worker.run` restores and saves
    the cache around any runner, this one included.

    A park request stops a non-side run at the next step boundary (a finished turn, after its tool calls): the run
    comes back `PARKED` (125), and `Worker.run` then holds the model for the person and
    resumes the same session with RESUME_PROMPT. Side runs (checkpoint/learn/review) never park - a checkpoint is the
    pause, not something to be interrupted by one.

    After a normal return the run leaves one log artifact under `paths.LOGS` (`<tid>-<phase>-<epoch>.log`): header
    (flow, phase, model, session, workspace), the prompt, one line per tool call, the report and the stop reason.
    `RunResult.log` is that path. A full disk must not fail a task: if the write cannot happen, the result is
    returned with `log` left empty.
    """
    from . import models as modellib
    from . import runtime
    from .runtime import mcp as mcp_mod
    from .runtime import skills as skills_mod
    from .runtime import web as web_mod
    home = Path(flow.home)
    home.mkdir(parents=True, exist_ok=True)
    side = phase.startswith(("checkpoint", "learn", "review"))   # read-only side runs
    (home / "ariadne_phase").write_text("plan" if side else phase, encoding="utf-8")
    (home / "ariadne_task").write_text(tid, encoding="utf-8")            # read by the jobs MCP server
    (home / "ariadne_workspace").write_text(str(workspace), encoding="utf-8")
    name = session or f"{tid}-{phase.replace(':', '-')}"
    pool = None
    cfg = flowlib.mcp_server_config(flow)
    if cfg:
        pool = mcp_mod.Pool(cfg, plan_allowed=flow.plan_tools)
    box = skills_mod.Box(flow)
    search = web_mod.Search()    # web_search in every run; it holds no server, so there is nothing to close
    events = []
    try:
        r = runtime.run(prompt, home=flow.home, workspace=workspace, phase=phase, model=model or flow.model,
                        session=name, max_turns=flow.max_turns.get(phase, 40),
                        budget=int(flow.run_budget.get(phase, flow.run_budget.get("execute", 1800))),
                        mcp=pool, skills=box, web=search,
                        context_tokens=int(modellib.load().context.get("window") or 65536),
                        checkpoint=None if side else park.requested,   # park at a step boundary; side runs never park
                        on_event=lambda kind, detail: events.append((kind, detail)))
    finally:
        if pool is not None:
            pool.close()
    code = (PARKED if r.stopped == "parked"
            else 124 if r.stopped == "budget"
            else TURNS if r.stopped == "max_turns"
            else (0 if r.stopped == "" else 1))
    if pool is not None and pool.errors:
        r.text = f"MCP servers unavailable: {len(pool.errors)} (see runtime log)\n" + r.text
    if not r.text.strip():
        r.text = f"STOPPED ({r.stopped}) after {r.turns} turn(s); continue from the files as they are."
    return RunResult(r.text, code, _run_log(flow, phase, model, name, str(workspace), tid, prompt, events, r), name)


def _run_log(flow, phase, model, name, workspace, tid, prompt, events, r):
    """The per-run log artifact; '' when it cannot be written (a full disk must not fail a task)."""
    try:
        log = paths.LOGS / f"{tid}-{phase.replace(':', '-')}-{int(time.time())}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"flow: {flow.name}", f"phase: {phase}", f"model: {model or flow.model}",
                 f"session: {name}", f"workspace: {workspace}", "", "PROMPT:", prompt, ""]
        lines += [f"tool {detail}" for kind, detail in events if kind == "tool"]
        lines += ["", "REPORT:", r.text, ""]
        if r.stopped:
            lines.append(f"stopped={r.stopped}")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(log)
    except OSError:
        return ""


PARKED = 125  # exit code of a run stopped by a park request
TURNS = 126   # exit code of a run stopped by its turn limit (not failure: the gates decide)


# ---------- prompts ----------

PLAN_PROMPT = """You are the {flow} worker of Ariadne, a local agent harness. This is the PLAN phase: you may only read
(files, search, shared memory, git status/diff/log). Nothing is changed until a person approves your plan.

TASK (from {source}):
{text}

WORKSPACE: {workspace}
{feedback}
HOW THIS FLOW WORKS (flows/{flow}/FLOW.md - the coordination this plan must follow; it is the knowledge a small
model cannot invent, so follow it unless the task clearly needs otherwise, and say why if you do not):
{flow_brief}

SHARED SKILLS for this flow (written by the larger models from earlier tasks and the person's feedback; they encode
how this work is actually done here. Read the ones that apply with skill_view before planning, and follow them):
{skills_block}

CHECK GATES agreed with the person (the task is done only when every one passes; plan so that each will):
{gates}

SHARED MEMORY (what earlier tasks recorded):
{memory}

After sign-off the execute phase will have only these tools: {exec_tools}. Plan only steps those tools can do.

MODELS you may assign to steps (one per step; {default_model} if a step does not need anything else):
{models}
Agent models do a step themselves. A generate model drafts text for a step (the agent asks it through
generate_text); an image model renders images (generate_image). Prefer the MoE models: on this machine they read
and write several times faster, so steps finish sooner. You ({planner}) are the planner; assign yourself or another
dense model only to a step that needs the deepest reasoning (hard debugging, tricky design decisions), and say why.
Each step (or run of steps on one model) executes in a fresh session that only gets a summary of earlier steps, so
every step must leave its output in files; never plan a "think only" step whose result a later step on another
model has to write down. Fewer model changes is better: switch models only where it clearly pays.
Work that can run for minutes (ingest, embedding, installs, builds, evals, full test suites) is not run by the model:
the step writes a script and submits it as a job when the execute tools include submit_job (the jobs skill), else it
follows the long-jobs skill. Plan it as: write the script with a sample mode -> job: sample run -> job: full run
(resumable, writes a report file) -> check the report. Each job's result wakes the model to do the next step.

Investigate just enough to plan well (look at the relevant files). Then reply with a backbrief in exactly this form:

MISSION: <one sentence: what will be true when this is done>
FLOW: {flow}
STEPS:
1. <step> - tools: <tools it uses> - model: <model name from MODELS>
2. ...
GATES: <each gate G1..Gn, and which step makes it pass>
RISKS: <what could go wrong, or 'none'>
QUESTIONS: <anything the person must answer first, or 'none'>

After that document, end with one fenced json block and nothing after it. The harness reads the block to build the
sign-off sheet; it must be valid JSON with exactly these keys:

```json
{{"mission": "one line", "steps": [{{"n": 1, "text": "one step"}}],
 "gates": ["which step makes each gate pass"], "risks": ["..."], "questions": ["..."]}}
```

Do not name models in the block: the person chooses the task's model at sign-off.
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
{jobs_rule}
- At the end, record in shared memory (memory_record) anything a later task should know about this workspace.
- Finish with a short report: what you changed, how you verified it.
"""

JOBS_RULE = """- You write code and scripts; Ariadne runs the heavy work. Installs, ingest, embedding, builds, evals, full test
  suites, downloads: write the script, call submit_job (jobs tools), then end your turn with
  'JOB SUBMITTED: <id>'. You are unloaded while it runs and woken here with the result. Quick commands (read,
  grep, git status, one test file) stay in the terminal. Follow the jobs skill."""
NO_JOBS_RULE = """- Anything that may take more than 2 minutes: follow the long-jobs skill (sample first, then terminal
  background=true with progress in a log, wait with process_manage, resume rather than restart)."""


def jobs_rule(flow):
    return JOBS_RULE if "jobs" in flow.mcp_servers else NO_JOBS_RULE


def skills_block(flow_name: str) -> str:
    """The flow's shared skills, name and description, for the plan prompt.

    These are the skills the larger models wrote from earlier tasks and the person's feedback. Loading them into
    the plan is what makes that writing steer the next run instead of sitting in a folder.
    """
    from . import skills as skilllib
    try:
        rows = skilllib.list_skills(flow_name)
    except Exception:
        return "(none yet)"
    return "\n".join(f"- {r['name']}: {r['description']}" for r in rows) or "(none yet)"


def _install_system_tools(names):
    """Install the system tools the backbrief named. Reached only after the person approved the plan."""
    from . import deps
    deps.install(system=True)


# ---------- model plan: a model per step, suggested by the planner, locked at sign-off ----------

STEP_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
MODEL_RE = re.compile(r"\bmodel:\s*`?([A-Za-z0-9][\w.\-]*)", re.I)
SECTION_RE = re.compile(r"^[A-Z][A-Z ]+:")


def parse_model_plan(plan_text, flow, catalog, default_model=None):
    """The backbrief's steps and the model each names; a missing or unknown name gets the task's explicit model."""
    default = default_model or flow.step_model
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
            notes.append(f"step {m.group(1)} named '{name}', which is not in the catalog; using {flow.step_model}")
            name = ""
        steps.append({"n": int(m.group(1)), "text": body, "model": name or default})
    return {"steps": steps, "agent": default, "notes": notes}


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
    mp["chain"] = chain_for(mp, cat)      # a model change changes the sessions; the recorded chain follows
    return mp


def model_summary(mp):
    return ", ".join(f"{s['n']}={s['model']}" for s in mp["steps"]) or f"all={mp['agent']}"


def chain_for(mp, catalog):
    """The plan as an explicit chain of sessions: consecutive steps one agent model owns share one session.

    A step that names a generate or image model is not a session of its own - the agent runs it through a tool - so
    it belongs to the agent that owns the run it sits in. The chain is recorded in the plan (`models.chain`) at
    sign-off, so the person sees how many sessions a plan costs before approving it, and execution reads the same
    function instead of inventing a second reading of the plan.
    """
    chain = []
    for s in mp["steps"]:
        m = catalog.get(s["model"])
        agent = m.name if m.kind == "agent" else mp["agent"]
        if chain and chain[-1]["agent"] == agent:
            chain[-1]["steps"].append(s["n"])
        else:
            chain.append({"agent": agent, "steps": [s["n"]]})
    return chain or [{"agent": mp["agent"], "steps": []}]


def needed_models(mp, catalog):
    """What a run needs: the chain's agents, plus any generate/image model a step calls as a tool."""
    agents = [link["agent"] for link in chain_for(mp, catalog)]
    tools = [s["model"] for s in mp["steps"] if catalog.get(s["model"]).kind != "agent"]
    return list(dict.fromkeys(agents + tools or [mp["agent"]]))


def needed_servers(mp, catalog):
    """MCP servers the chosen models are reached through (image -> image, generate -> text)."""
    kinds = {catalog.get(s["model"]).kind for s in mp["steps"]}
    return [srv for kind, srv in (("image", "image"), ("generate", "text")) if kind in kinds]


def model_block(mp, flow, catalog):
    """What the harness adds to the backbrief: the model per step, the sessions, what will be fetched, what is
    missing."""
    out = ["", "MODEL PLAN (sign-off locks these; anything not installed is fetched before step 1):"]
    out.append(f"  task model: {mp.get('agent')}")
    for s in mp["steps"] or [{"n": "all", "model": mp["agent"]}]:
        m = catalog.get(s["model"])
        state = "installed" if m.installed() else f"not installed, {m.size_gb:g} GB"
        via = "" if m.kind == "agent" else f", run by {mp['agent']} through its tool"
        out.append(f"  step {s['n']}: {m.name} ({m.kind}, {state}{via})")
    chain = mp.get("chain") or chain_for(mp, catalog)
    if len(chain) > 1:
        out.append(f"  {len(chain)} sessions (a session per agent model; each gets a carry-forward note):")
        out += [f"    session {i}: {c['agent']} - steps {', '.join(str(n) for n in c['steps'])}"
                for i, c in enumerate(chain, 1)]
    out += [f"  note: {n}" for n in mp["notes"]]
    todo = [n for n in needed_models(mp, catalog) if not catalog.get(n).installed()]
    if todo:
        out.append("TO FETCH AFTER SIGN-OFF: " + ", ".join(f"{n} ({catalog.get(n).size_gb:g} GB)" for n in todo))
    gaps = missing_tools(mp, flow, catalog)
    need = missing_system(flow)
    if need:
        # Named here, in the plan, because approving the brief is what authorises the download.
        out.append("TO INSTALL AFTER SIGN-OFF: " + "; ".join(f"{m} ({flowlib.install_hint(m)})" for m in need))
    bad = missing_servers(mp, flow, catalog)
    if bad:
        out.append("PLAN ERROR - the flow does not enable MCP server(s): " + ", ".join(bad)
                   + f" (add them to flows/{flow.name}/flow.yaml)")
    if gaps and not need:
        out.append("MISSING TOOLS (execution will not start until they are there): " + "; ".join(gaps))
    out.append("Change a model: approve with --model STEP=NAME (or all=NAME), or revise. Models: python -m ariadne models")
    return "\n".join(out)


def missing_system(flow):
    """System tools the flow declares and this machine lacks (installable, named in the backbrief)."""
    return flowlib.missing_requirements(flow)


def missing_servers(mp, flow, catalog):
    """MCP servers the chosen models need but the flow does not enable - a planning error, not a download."""
    return [s for s in needed_servers(mp, catalog) if s not in flow.mcp_servers]


def missing_tools(mp, flow, catalog):
    gaps = [f"{m} ({flowlib.install_hint(m)})" for m in missing_system(flow)]
    gaps += [f"MCP server '{s}' (add it to mcp_servers in flows/{flow.name}/flow.yaml)"
             for s in missing_servers(mp, flow, catalog)]
    return gaps


def step_scope(steps, chain_len, catalog):
    """What an execute run is told to do now: its steps (when the plan splits) and how to use other models."""
    lines = []
    if chain_len > 1:
        lines.append(f"NOW DO STEP{'S' if len(steps) > 1 else ''} {', '.join(str(s['n']) for s in steps)} ONLY. "
                     "Earlier steps are done; later steps run separately.")
    for s in steps:
        m = catalog.get(s["model"])
        if m.kind == "generate":
            lines.append(f"Step {s['n']}: have {m.name} write the text: generate_text(model='{m.name}', prompt=...).")
        elif m.kind == "image":
            lines.append(f"Step {s['n']}: render with generate_image(model='{m.name}', ...).")
    return ("\n" + "\n".join(lines) + "\n") if lines else ""


CHECKPOINT_PROMPT = """CHECKPOINT: {reason}. Pause here and do not call any tools.
This conversation is about to be replaced by what you write now. Write the handoff brief the next worker needs to
carry on without it:

SITUATION: what this session is working on, in which workspace, for which task
DONE: what has been done (files changed, commands run, results), with exact paths and names
STATE: decisions made, facts learned, what is verified and what is not
OPEN: what is left to do, problems, failing checks
{extra}
Facts only, complete but brief (under 600 words)."""

REVIEW_PROMPT = """QA REVIEW. You are checking finished work against the gates the person set. Inspect the workspace
({workspace}) with your read tools; do not change anything. Be strict: a gate passes only if you saw the evidence.

TASK: {text}

GATES TO REVIEW:
{gates}

Reply with one line per gate, exactly:
G<n>: PASS - <evidence>    or    G<n>: FAIL - <what is missing or wrong>"""

JOB_RESULT_PROMPT = """You were asleep while Ariadne ran the job(s) you submitted, with the machine to itself. Results:

{results}

Read them and continue the approved plan from here: fix and resubmit if a job failed (resume, do not start over),
otherwise go on to the next step. Heavy work again goes through submit_job."""

RESUME_PROMPT = """You were paused at a step boundary so the person could use the model. Continue the same task where
you left off. If your last tool call has no result, run it again; re-read a file before editing it."""

RETRY_PROMPT = """GATES FAILED. This is the same session and the same approved plan; nothing has been thrown away.
These checks must pass and do not:

{failures}

The cause may be in any step of the plan, not only the last one that ran: find the step that owns each failure and
fix it without redoing steps that are already proven. Do not improvise a different plan; if the plan itself is
wrong, reply starting with 'OFF-PLAN:' and the reason. Finish with a short report: what you changed, how you
verified it."""

HANDOFF = """SESSION HANDOFF - the earlier work in this session, compressed at a checkpoint. Trust it; re-read files
only where you need detail.
{summary}

---

"""

ROUTE_PROMPT = """Pick the flow for this task. Flows:
{flows}

Task: {text}

Reply with only the flow name."""


# ---------- the worker ----------

class Worker:
    def __init__(self, store=None, memory=None, flows=None, runner=runtime_run, router_model="router", llm_chat=None,
                 catalog=None, installer=None, on_installed=None, kv=None, job_runner=None, unload=None,
                 install_tools=None, clock=None):
        from . import kvcache
        real = runner is runtime_run
        # Jobs run for real only with a real runner; tests pass a fake that never unloads the model server.
        self.job_runner = job_runner or (jobs.run if real else
                                         (lambda j, db: jobs.run(j, db, unload=lambda: True, poll=0.05)))
        # Same rule for freeing VRAM: only a real runner has a model server behind it.
        self.unload = unload or (jobs.unload_models if real else (lambda: True))
        self.kv = kv or (kvcache.default() if real else kvcache.NoKVCache())
        from . import models as modellib
        self.catalog = catalog or modellib.load()
        self.installer = installer or modellib.install
        self.install_tools = install_tools or _install_system_tools
        self.on_installed = on_installed or _reload_models
        self.store = store or Store()
        self.memory = memory or Memory()
        self.flows = flows or flowlib.load_flows()
        self.runner = runner
        self.router_model = router_model
        self.llm_chat = llm_chat or llm.chat
        self.now = clock or time.time   # the task wall clock reads through this, so a test can spend time

    def route(self, t):
        """The flow, or None with the reason: a task outside the approved set is rejected, never guessed at."""
        if t["flow"]:
            if t["flow"] in self.flows:
                return t["flow"], "given by the task"
            return None, f"'{t['flow']}' is not an approved flow"
        if len(self.flows) == 1:
            return next(iter(self.flows)), "only flow"
        listing = "\n".join(f"- {f.name}: {f.when}" for f in self.flows.values())
        try:
            answer = self.llm_chat(self.router_model, [{"role": "user", "content": ROUTE_PROMPT.format(
                flows=listing, text=t["text"])}]).lower()
        except Exception as e:  # router down: say so, do not invent a flow
            self.store.event(t["id"], "route", f"router failed ({e})")
            return None, f"the router could not run ({e})"
        for name in self.flows:
            if re.search(rf"\b{re.escape(name)}\b", answer):
                return name, f"router said '{answer[:60]}'"
        return None, f"the router named no approved flow (it said {answer[:60]!r})"

    def workspace(self, t):
        ws = t["workspace"] or str(paths.STATE / "workspace")
        Path(ws).mkdir(parents=True, exist_ok=True)
        return ws

    def plan(self, t):
        name, why = self.route(t)
        if not name:
            approved = ", ".join(self.flows)
            self.store.update(t["id"], status="rejected",
                              result=(f"No approved flow: {why}.\n"
                                      f"Approved flows: {approved}.\n"
                                      "Give the task again with --flow <name>, or reword it so the router can pick "
                                      "one of them."))
            self.store.event(t["id"], "route", f"rejected: {why}")
            return
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
        planner = self.catalog.get((t.get("model") or "").strip() or flow.model)
        if not planner.installed():
            msg = (f"flow '{name}' plans and works with {planner.name}, which is not installed "
                   f"({planner.size_gb:g} GB). Install it (python -m ariadne models install {planner.name}), "
                   f"then revise the task to retry.")
            self.store.update(t["id"], status="needs_attention", result=msg)
            self.store.event(t["id"], "route", f"{flow.model} not installed")
            return
        ws = self.workspace(t)
        hits = self.memory.recall(f"{t['text']} {ws}", limit=5)
        feedback = f"\nFEEDBACK ON THE LAST PLAN (address it):\n{t['feedback']}\n" if t["feedback"] else ""
        default_model = (t.get("model") or "").strip() or flow.step_model
        prompt = PLAN_PROMPT.format(flow=name, source=t["source"], text=t["text"], workspace=ws,
                                    gates=gates_text(json.loads(t.get("gates") or "[]")) or "(none)",
                                    feedback=feedback, memory=format_hits(hits),
                                    flow_brief=flow.brief or "(this flow has no FLOW.md)",
                                    skills_block=skills_block(name),
                                    exec_tools=", ".join(flow.execute_toolsets + [f"{m} (MCP)" for m in flow.mcp_servers]),
                                    models=self.catalog.text(), default_model=default_model, planner=planner.name)
        self.store.event(t["id"], "plan", f"started ({len(hits)} memories recalled)")
        r = self.run(flow, "plan", prompt, ws, t, planner.name, "plan")
        if r.exit_code != 0 or not r.text:
            self.store.update(t["id"], status="failed", error=f"plan run failed (exit {r.exit_code}); log {r.log}")
            self.store.event(t["id"], "plan", f"failed, log {r.log}")
            return
        try:
            plan = protocol.parse(r.text, default_model)
            mp = {"steps": plan["steps"], "agent": default_model, "notes": []}
            mp["chain"] = chain_for(mp, self.catalog)
            document = render.backbrief(plan)
            self.store.update(t["id"], plan_json=protocol.to_json(plan))
        except protocol.PlanError as e:
            # One release of tolerance: an older planner that answers in prose still reaches sign-off, and the
            # backbrief says the structure was read from the text.
            mp = parse_model_plan(r.text, flow, self.catalog, default_model=default_model)
            mp["notes"].append(f"the reply had no usable JSON plan ({e}); read from the text instead")
            document = r.text
        self.store.update(t["id"], status="awaiting_signoff",
                          plan=document.rstrip() + "\n" + model_block(mp, flow, self.catalog),
                          models=json.dumps(mp))
        self.store.event(t["id"], "backbrief", "ready for sign-off")
        self.memory.record("task", t["id"], f"{t['text']}\nstatus: awaiting sign-off",
                           [("uses_flow", "flow", name), ("in_workspace", "workspace", ws)])

    def segment(self, t, flow):
        """The session row and the Hermes session (segment) the next run continues: <name>~<n>. Moving to another
        flow starts a new segment (its own Hermes home) seeded with the last handoff brief."""
        s = self.store.session(t.get("session") or t["id"], t.get("source", ""))
        if s["flow"] != flow.name:
            seg = s["segment"] + 1 if s["flow"] else s["segment"]
            self.store.session_update(s["name"], flow=flow.name, segment=seg, fresh=1 if s["summary"] else 0,
                                      hermes_id="")
            s = self.store.session(s["name"])
        return s, f"{s['name']}~{s['segment']}"

    def run(self, flow, phase, prompt, ws, t, model, scope):
        """One Hermes run in the task's session segment on `model`. A fresh segment's first run is seeded with the
        handoff brief. The KV cache for (segment, step, model) is woken first and parked after (kvcache.py)."""
        s, title = self.segment(t, flow)
        seeded = bool(s["fresh"] and s["summary"])
        if seeded:
            prompt = HANDOFF.format(summary=s["summary"]) + prompt
        # Within a segment the Hermes session is resumed (same model and tools by construction: a segment is one
        # phase on one model); a new segment starts a new Hermes session.
        # The stored id is "<phase>/<model>|<hermes id>": resume only a session started for the same phase and model.
        sig = f"{phase.split(':')[-1]}/{model}"
        stored_sig, _, stored_id = (s["hermes_id"] or "").partition("|")
        resume = stored_id if stored_id and stored_sig == sig else None
        side = phase.startswith(("checkpoint", "learn", "review"))
        if park.requested() and not side:  # parked by the person: hold before starting anything new
            self._hold(t, model)
        # Wake a parked cache only when resuming: a new Hermes session has a new prefix, nothing would match.
        note = self.kv.restore(title, model, scope) if resume else ""
        if note:
            self.store.event(t["id"], "kv", f"{model}: {note}")
        r = self.runner(flow, phase, prompt, ws, t["id"], model=model, session=resume)
        # Park only what a later run resumes (plan and execute sessions); side runs are not resumed.
        note = self.kv.save(title, model, scope) if not side else ""
        if note:
            self.store.event(t["id"], "kv", f"{model}: {note}")
        while r.exit_code == PARKED:  # stopped at a step boundary on request: wait, then continue the same session
            self.store.event(t["id"], "park", f"stopped at a step boundary on {model}; the model is free")
            self._hold(t, model)
            note = self.kv.restore(title, model, scope) if r.session_id else ""
            if note:
                self.store.event(t["id"], "kv", f"{model}: {note}")
            again = RESUME_PROMPT if r.session_id else prompt
            r = self.runner(flow, phase, again, ws, t["id"], model=model, session=r.session_id or resume)
            note = self.kv.save(title, model, scope)
            if note:
                self.store.event(t["id"], "kv", f"{model}: {note}")
        if not side:
            r = self._run_jobs(flow, phase, ws, t, model, scope, title, r, resume)
        if r.exit_code == 0:
            if phase.startswith(("learn", "review")):  # side trips: the segment stays as it was
                return r
            dirty = 0 if phase.startswith("checkpoint") else 1
            self.store.session_update(s["name"], fresh=0, dirty=dirty,
                                      hermes_id=f"{sig}|{r.session_id}" if r.session_id else s["hermes_id"])
        return r

    MAX_JOB_CYCLES = 40

    def _run_jobs(self, flow, phase, ws, t, model, scope, title, r, resume):
        """The callback loop: while the model has submitted jobs, run them with the model unloaded (its KV cache is
        already parked), then wake the same Hermes session with the results. Ends when a run submits no job."""
        cycles = 0
        while cycles < self.MAX_JOB_CYCLES:
            pending = jobs.for_task(t["id"], "pending", self.store.db_path)
            if not pending:
                return r
            cycles += 1
            results = []
            for j in pending:
                self.store.event(t["id"], "job", f"{j['id']} started: {j['why'] or j['command']} (model unloaded)")
                j = self.job_runner(j, self.store.db_path)
                res = json.loads(j.get("result") or "{}")
                self.store.event(t["id"], "job", f"{j['id']} {j['status']}: exit {j['exit_code']} in "
                                                 f"{res.get('seconds')} s")
                results.append(jobs.result_text(j))
            session = r.session_id or resume
            note = self.kv.restore(title, model, scope) if session else ""
            if note:
                self.store.event(t["id"], "kv", f"{model}: {note}")
            prompt = JOB_RESULT_PROMPT.format(results="\n\n".join(results))
            r = self.runner(flow, phase, prompt, ws, t["id"], model=model, session=session)
            note = self.kv.save(title, model, scope)
            if note:
                self.store.event(t["id"], "kv", f"{model}: {note}")
        self.store.event(t["id"], "job", f"stopped after {self.MAX_JOB_CYCLES} job cycles")
        return r

    def _hold(self, t, model):
        """Parked: give the model to the person until they resume (never resumes on its own)."""
        by = (park.requested() or {}).get("by", "")
        park.mark_parked(t["id"], model)
        self.store.event(t["id"], "park", by if by.startswith("login needed") else
                         "parked: waiting for resume (desktop button or `python -m ariadne park --resume`)")
        park.wait_resumed()
        self.store.event(t["id"], "park", "resumed")
        # Nothing to regenerate on resume: the runtime reads the flow's servers and browser setting on every run.

    def checkpoint(self, t, flow, ws, model, reason, closes="execute", extra=""):
        """Pause and compress at a phase boundary: the model that just worked (still loaded, cache hot) writes a
        handoff brief; the next run starts a new segment seeded with it. Skipped when nothing ran since the last
        checkpoint. A failed checkpoint just leaves the session uncompressed."""
        s, title = self.segment(t, flow)
        if not s["dirty"]:
            return
        r = self.run(flow, f"checkpoint:{closes}", CHECKPOINT_PROMPT.format(reason=reason, extra=extra), ws, t,
                     model, "checkpoint")
        if r.exit_code != 0 or not r.text.strip():
            self.store.event(t["id"], "compress", f"{reason}: skipped (exit {r.exit_code}); continuing uncompressed")
            return
        self.store.session_update(s["name"], segment=s["segment"] + 1, summary=r.text.strip()[:12000], fresh=1, dirty=0,
                                  hermes_id="")
        self.kv.drop(title)
        self.store.event(t["id"], "compress", f"{reason}: {title} -> {s['name']}~{s['segment'] + 1} "
                                              f"(handoff {len(r.text)} chars)")

    def qa(self, t, flow, ws, model):
        """QA after execution: the flow's checks, the task's command gates, then a reviewer run for the review gates.
        Returns failure descriptions ([] = every gate passed)."""
        gates = json.loads(t.get("gates") or "[]")
        failures = self.run_checks(flow, ws, [g["text"] for g in gates if g["type"] == "run"])
        review = [(i, g) for i, g in enumerate(gates, 1) if g["type"] == "review"]
        if review:
            r = self.run(flow, "review:plan", REVIEW_PROMPT.format(
                workspace=ws, text=t["text"], gates="\n".join(f"G{i}. {g['text']}" for i, g in review)),
                ws, t, model, "review")
            verdicts = dict(re.findall(r"G(\d+)\s*:\s*(PASS|FAIL)\b", r.text, re.I))
            for i, g in review:
                v = verdicts.get(str(i), "").upper()
                if v != "PASS":
                    line = next((l for l in r.text.splitlines() if re.match(rf"\s*G{i}\s*:", l)), "no verdict")
                    failures.append(f"G{i} [review] {g['text']}: {line.strip()[:500]}")
            self.store.event(t["id"], "qa", f"review: {sum(1 for i, _ in review if verdicts.get(str(i), '').upper() == 'PASS')}"
                                            f"/{len(review)} gates passed")
        return failures

    def run_checks(self, flow, ws, extra_cmds=()):
        failures = []
        for check in list(flow.checks) + list(extra_cmds):
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
        """Before step 1: every tool the plan needs is there and every locked model is installed.

        The backbrief named anything missing, so approving it authorised the download: models are fetched and
        system tools installed. Only a configuration error still stops the task.
        """
        bad = [f"MCP server '{s}' (add it to mcp_servers in flows/{flow.name}/flow.yaml)"
               for s in missing_servers(mp, flow, self.catalog)]
        too_big = [n for n in needed_models(mp, self.catalog) if not self.catalog.fits(self.catalog.get(n))
                   and self.catalog.get(n).kind != "image"]
        if too_big:
            b = self.catalog.active_budget()
            bad.append(f"{', '.join(too_big)} too large for the '{b['profile']}' resource profile "
                       f"(max {b['max_model_gb']} GB; python -m ariadne resources shared)")
        if bad:
            return "Execution did not start; missing: " + "; ".join(bad) + ". Fix that, then approve again."
        need = missing_system(flow)
        if need:
            self.store.event(t["id"], "install", "installing after sign-off: " + ", ".join(need))
            try:
                self.install_tools(need)
            except Exception as e:
                return (f"Execution did not start: could not install {', '.join(need)}: {e}. Install it "
                        f"(python -m ariadne install --system), then approve again.")
            still = missing_system(flow)
            if still:
                return (f"Execution did not start; still missing {', '.join(still)}. Install it, then approve "
                        "again.")
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

    def _sleep(self, t, why):
        """Give the machine back: unload the orchestrator model until a new plan is needed.

        The planner is the largest model in the flow and is not used again until re-planning (revise, off-plan).
        Holding it while the executor works is what made one GPU thrash: the worker's own model should be the only
        thing on the card while a task runs.
        """
        try:
            freed = self.unload()
        except Exception as e:
            self.store.event(t["id"], "vram", f"could not unload the orchestrator model: {e}")
            return
        if freed:
            self.store.event(t["id"], "vram", f"orchestrator model unloaded ({why}); it waits for the task")

    def execute(self, t):
        flow = self.flows.get(t["flow"])
        if not flow:
            self.store.update(t["id"], status="failed", error=f"flow '{t['flow']}' no longer exists")
            return
        mp = json.loads(t["models"]) if t.get("models") else {"steps": [], "agent": flow.step_model, "notes": []}
        problem = self.prepare(t, flow, mp)
        if problem:
            self.store.update(t["id"], status="needs_attention", result=problem)
            self.store.event(t["id"], "prepare", problem[:300])
            return
        ws = self.workspace(t)
        self.checkpoint(t, flow, ws, flow.model, "plan approved", closes="plan",
                        extra="Include the approved plan's steps verbatim under OPEN.")
        # The brief is delivered and signed off; the planner is not needed again until a re-plan.
        self._sleep(t, "the plan is signed off")
        chain = chain_for(mp, self.catalog)
        budget = int(getattr(flow, "task_budget", 0) or 0)
        if budget:
            self.store.event(t["id"], "budget", f"task wall clock: {budget} s of worker time from now")
        reports, last = [], chain[-1]
        # One session per link, and a link exists only because the plan changes agent model.
        for link in chain[:-1]:
            if self._expired(t, flow):
                return self._out_of_time(t, flow, ws, reports, self._label(link, len(chain)))
            r = self._run_session(t, flow, ws, mp, link, 1, len(chain), reports, "")
            if r is None:                      # the outcome is already recorded (off-plan, or a run that died)
                return
            reports.append(r.text)
            self.checkpoint(t, flow, ws, link["agent"], f"{self._label(link, len(chain))} done")
        # Gates at the edge: they run after the last link, and a failure resumes this same session with the reason.
        history, attempts, failures = [], 0, []
        while True:
            if self._expired(t, flow):
                return self._out_of_time(t, flow, ws, reports, self._label(last, len(chain)))
            attempts += 1
            r = self._run_session(t, flow, ws, mp, last, attempts, len(chain), reports, failures)
            if r is None:
                return
            if self._expired(t, flow):
                # The work is in; there is no time left to run the reviewer, so end on the gates a script can run.
                return self._out_of_time(t, flow, ws, reports + [r.text], self._label(last, len(chain)))
            failures = self.qa(t, flow, ws, last["agent"])
            if not failures:
                self.checkpoint(t, flow, ws, last["agent"], "QA passed: every gate")
                has_cmds = flow.checks or any(g["type"] == "run" for g in json.loads(t.get("gates") or "[]"))
                self.store.event(t["id"], "checks", "passed (every gate)" if has_cmds else
                                 "passed (review gates only; no command gates)")
                self._finish(t, flow, ws, "done", "\n\n".join(reports + [r.text]))
                return
            self.store.event(t["id"], "checks", f"failed: {failures[0][:300]}")
            # Loop end: the gates pass, max_iterations is reached, or two iterations in a row fail as many gates as
            # before (no progress: more of the same will not get there).
            history.append(len(failures))
            stalled = len(history) >= 3 and history[-1] >= history[-2] >= history[-3]
            if attempts >= flow.max_iterations or stalled:
                why = "no progress in the last two iterations" if stalled else f"{attempts} iterations"
                return self._finish(t, flow, ws, "failed", "\n\n".join(reports + [r.text]),
                                    f"gates still failing after {why}:\n" + "\n".join(failures))
            self.store.event(t["id"], "iterate", f"{len(failures)} gate(s) failing; iteration {attempts + 1} "
                                                 f"of at most {flow.max_iterations}")

    @staticmethod
    def _label(link, chain_len):
        return f"steps {', '.join(str(n) for n in link['steps'])}" if chain_len > 1 else "plan"

    def _run_session(self, t, flow, ws, mp, link, attempt, chain_len, reports, failures=()):
        """One runtime run for one link of the chain, in the session that link owns.

        Start with the approved plan; a later attempt resumes the *same* session and is told only what failed. Returns
        the result, or None when the task has already been stopped (off-plan, or a run that died).
        """
        steps = [s for s in mp["steps"] if s["n"] in link["steps"]]
        label = self._label(link, chain_len)
        self.store.event(t["id"], "execute", f"{label} on {link['agent']}, attempt {attempt}")
        if attempt == 1:
            prompt = EXEC_PROMPT.format(flow=flow.name, text=t["text"], workspace=ws, jobs_rule=jobs_rule(flow),
                                        plan=t["plan"], extra=step_scope(steps, chain_len, self.catalog))
        else:
            prompt = RETRY_PROMPT.format(failures="\n".join(failures))
        r = self.run(flow, "execute", prompt, ws, t, link["agent"],
                     "step-" + "-".join(str(s["n"]) for s in steps) if steps else "steps-all")
        out_of = ("time" if r.exit_code == 124 else "turns" if r.exit_code == TURNS else "")
        if out_of:
            # Out of time or turns is not out of options: what it wrote stays and the gates decide. An unfinished
            # link is unfinished, and the next one (or QA) continues from the files it left behind.
            what = "run budget" if out_of == "time" else "turn limit"
            self.store.event(t["id"], "execute", f"{what} used up on {label} (attempt {attempt}); "
                                                 "keeping what it wrote")
            return RunResult(r.text.strip() or (f"STOPPED ({what} used up) before finishing; continue from the "
                                                "files as they are."), 0, r.log, r.session_id)
        if r.exit_code != 0 or not r.text:
            self._finish(t, flow, ws, "failed", "\n\n".join(reports + [r.text]),
                         f"execute run failed (exit {r.exit_code}); log {r.log}")
            return None
        if r.text.lstrip().upper().startswith("OFF-PLAN"):
            # The plan was wrong, not the work: `error` marks why, so approving sends the task back to planning
            # (a new backbrief) instead of re-running the plan that just failed.
            self.store.update(t["id"], status="needs_attention", result=r.text, error="off-plan")
            self.store.event(t["id"], "execute", "stopped: off-plan, back to the person for a new sign-off")
            self.checkpoint(t, flow, ws, link["agent"], "stopped off-plan", extra="Say why under OPEN.")
            return None
        return r

    def _expired(self, t, flow):
        """Is the task's wall clock spent? `task_budget` seconds of worker time, from flow.yaml (0 = no limit).

        Time waiting in the queue or for a sign-off does not count: `claim_next` restarts the clock every time the
        worker picks the task up, so a brief that sits overnight is not timed out the moment it is approved.
        """
        budget = int(getattr(flow, "task_budget", 0) or 0)
        started = float(t.get("run_started") or 0)
        return bool(budget and started and self.now() - started >= budget)

    def _out_of_time(self, t, flow, ws, reports, label=""):
        """The wall clock is spent between phases: stop running the model and let the gates that need no model decide.

        What was written stays in the workspace. Command gates run; a review gate needs a reviewer run, which is
        exactly the work there is no time left for, so it is named as not reviewed. All commands pass and nothing
        needs a reviewer -> the task is `done`; otherwise it ends `timed_out` with the gate results and the reason.
        """
        budget = int(getattr(flow, "task_budget", 0) or 0)
        self.store.event(t["id"], "timeout",
                         f"wall clock spent ({budget} s) during {label or 'the run'}; keeping what was written and "
                         "running the gates a script can run")
        gates = json.loads(t.get("gates") or "[]")
        failures = self.run_checks(flow, ws, [g["text"] for g in gates if g["type"] == "run"])
        unreviewed = [f"G{i} [review] {g['text']}" for i, g in enumerate(gates, 1) if g["type"] == "review"]
        body = "\n\n".join(r for r in reports if r)
        if not failures and not unreviewed:
            self.store.event(t["id"], "checks", "passed (command gates, after the wall clock ran out)")
            self._finish(t, flow, ws, "done", (body + "\n\n" if body else "")
                         + f"Ran out of its {budget} s wall clock; every command gate passed, so it is done.")
            return
        detail = []
        if failures:
            detail.append("FAILING GATES:\n" + "\n".join(failures))
        if unreviewed:
            detail.append("NOT REVIEWED (no time left to run the reviewer):\n" + "\n".join(unreviewed))
        self.store.event(t["id"], "checks", f"out of time; {len(failures)} gate(s) failing, "
                                            f"{len(unreviewed)} not reviewed")
        self._finish(t, flow, ws, "timed_out", "\n\n".join(x for x in [body, *detail] if x),
                     f"the task used its {budget} s wall clock; the work so far is in the workspace")

    def _finish(self, t, flow, ws, status, result, error=""):
        self.store.update(t["id"], status=status, result=result or "", error=error)
        if (t.get("session") or t["id"]) == t["id"]:  # the task's own session ends with it; a caller's lives on
            self.kv.drop(self.segment(t, flow)[1])
        self.store.event(t["id"], "report", status + (f": {error[:300]}" if error else ""))
        self._sleep(t, "the task is finished")
        self.memory.record("task", t["id"], f"{t['text']}\nstatus: {status}\nresult: {(result or error)[:1500]}",
                           [("uses_flow", "flow", flow.name), ("in_workspace", "workspace", ws)])

    def run_once(self):
        t = self.store.claim_next(now=self.now())
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
