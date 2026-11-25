"""Task definitions: what a durable task says, how a flow template becomes one, and when it is due (docs/DESIGN.md).

A spec is a plain dict, stored as YAML (one file per signed version, `.ariadne/tasks/<id>/v<N>.yaml`), so a person can
read and diff exactly what runs. `validate()` is the single gate every front goes through: the orchestrator's draft,
an MCP `define(spec)`, and an edit all land here, and only a spec with no problems can be signed.

    name: googl-daily                    # unique, kebab-case
    flow: investigation
    workspace: C:/repos/ariadne/sandbox/googl
    goal: one sentence: what is true when a run is done
    params: {ticker: GOOGL}              # what the flow template asked for
    steps:
      - title: Gather prices
        instruction: ...                 # {param} placeholders are filled from params
        model: qwen3.6-35b-a3b           # optional: the flow's model
        tools: [file, terminal, jobs]    # a subset of the flow's toolsets and MCP servers
        outputs: [data/prices.csv]       # files the step must leave
        gate: {type: run, text: "python scripts/check_prices.py"}   # or {type: review, text: ...}; optional
    gates: [{type: review, text: ...}]   # task gates, checked after the last step
    trigger: {kind: now}                 # or {kind: at, at: 2026-11-25T07:00} or {kind: cron, cron: "0 7 * * 1-5"}
    tz: America/New_York
    budget_s: 3600                       # whole-run wall clock, worker time
    retries: 1                           # per step: retry once with the gate's reasons, then needs_you
"""
import copy
import re
from datetime import datetime
from pathlib import Path

from . import paths, yamlio

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
TRIGGERS = ("now", "manual", "at", "cron")
GATE_TYPES = ("run", "review")
DEFAULTS = {"trigger": {"kind": "manual"}, "tz": "America/New_York", "budget_s": 3600, "retries": 1,
            "params": {}, "gates": []}


class SpecError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def dump(spec) -> str:
    return yamlio.safe_dump(spec, sort_keys=False)


def load(text) -> dict:
    data = yamlio.safe_load(text) or {}
    if not isinstance(data, dict):
        raise SpecError(["a task definition is a YAML mapping"])
    return data


def _gate(g, where, problems):
    if g in (None, "", {}):
        return None
    if isinstance(g, str):
        g = {"type": "run", "text": g[4:].strip()} if g.startswith("run:") else {"type": "review", "text": g}
    if not isinstance(g, dict) or g.get("type") not in GATE_TYPES or not str(g.get("text", "")).strip():
        problems.append(f"{where}: a gate is {{type: run|review, text: ...}}")
        return None
    return {"type": g["type"], "text": str(g["text"]).strip()}


def _workspace_ok(ws: Path) -> bool:
    """Anywhere but Ariadne's own repository; its sandbox/ (ignored by git) is the exception."""
    ws, root, sandbox = ws.resolve(), paths.ROOT.resolve(), (paths.ROOT / "sandbox").resolve()
    inside_repo = ws == root or root in ws.parents
    return not inside_repo or ws == sandbox or sandbox in ws.parents


def tools_for(flow):
    """What a step of this flow may name: its execute toolsets and its MCP servers."""
    return list(flow.execute_toolsets) + list(flow.mcp_servers)


def validate(spec, flows, catalog=None):
    """Return the normalized spec, or raise SpecError naming every problem (all of them, not the first)."""
    s = copy.deepcopy(spec or {})
    problems = []
    for k, v in DEFAULTS.items():
        s.setdefault(k, copy.deepcopy(v))
    if not NAME_RE.match(str(s.get("name", ""))):
        problems.append("name: lowercase letters, digits and dashes, 2-49 characters")
    flow = flows.get(s.get("flow") or "")
    if not flow:
        problems.append(f"flow: one of {', '.join(flows)}")
    if not str(s.get("goal", "")).strip():
        problems.append("goal: one sentence saying what is true when a run is done")
    ws = str(s.get("workspace") or "").strip()
    if not ws:
        problems.append("workspace: the folder the steps work in")
    elif not _workspace_ok(Path(ws)):
        problems.append("workspace: not inside Ariadne's own repository (use a folder of its own, or sandbox/)")
    params = s.get("params") or {}
    if not isinstance(params, dict):
        problems.append("params: a mapping")
        params = {}
    texts = [str(s.get("goal", ""))] + [str(g) for g in s.get("gates") or []] + \
            [str(st.get(k, "")) for st in s.get("steps") or [] if isinstance(st, dict) for k in ("instruction", "gate")]
    used = {m for t in texts for m in re.findall(r"\{(\w+)\}", t)}
    missing = sorted(used - {k for k, v in params.items() if str(v).strip()})
    if missing:
        problems.append(f"params: the steps use {', '.join(missing)}, which have no value")
    steps = s.get("steps") or []
    if not isinstance(steps, list) or not steps:
        problems.append("steps: at least one step")
        steps = []
    allowed = tools_for(flow) if flow else []
    norm = []
    for i, st in enumerate(steps, 1):
        if not isinstance(st, dict):
            problems.append(f"step {i}: a mapping")
            continue
        where = f"step {i}"
        if not str(st.get("title", "")).strip():
            problems.append(f"{where}: a title")
        if not str(st.get("instruction", "")).strip():
            problems.append(f"{where}: an instruction")
        tools = list(st.get("tools") or (flow.execute_toolsets if flow else []))
        bad = [t for t in tools if t not in allowed]
        if flow and bad:
            problems.append(f"{where}: tools {', '.join(bad)} are not in flow {flow.name} ({', '.join(allowed)})")
        model = st.get("model") or (flow.step_model if flow else "")
        if catalog is not None and model:
            try:
                catalog.get(model)
            except Exception:
                problems.append(f"{where}: model {model} is not in the catalog")
        norm.append({"n": i, "title": str(st.get("title", "")).strip(), "instruction": str(st.get("instruction", "")).strip(),
                     "model": model, "tools": tools, "outputs": list(st.get("outputs") or []),
                     "gate": _gate(st.get("gate"), where, problems)})
    s["steps"] = norm
    s["gates"] = [g for g in (_gate(g, f"gate {i}", problems) for i, g in enumerate(s.get("gates") or [], 1)) if g]
    t = s.get("trigger") or {}
    if isinstance(t, str):
        t = {"kind": "cron", "cron": t} if len(t.split()) == 5 else {"kind": t}
    if t.get("kind") not in TRIGGERS:
        problems.append(f"trigger: kind is one of {', '.join(TRIGGERS)}")
    elif t["kind"] == "cron":
        try:
            from croniter import croniter
            croniter(str(t.get("cron", "")))
        except Exception:
            problems.append(f"trigger: '{t.get('cron')}' is not a cron expression (min hour day month weekday)")
    elif t["kind"] == "at":
        try:
            datetime.fromisoformat(str(t.get("at")))
        except Exception:
            problems.append("trigger: at is an ISO time, e.g. 2026-11-25T07:00")
    s["trigger"] = t
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(s["tz"])
    except Exception:
        problems.append(f"tz: '{s['tz']}' is not a time zone")
    if not isinstance(s.get("budget_s"), int) or s["budget_s"] < 60:
        problems.append("budget_s: whole seconds, at least 60")
    if not isinstance(s.get("retries"), int) or not 0 <= s["retries"] <= 4:
        problems.append("retries: 0 to 4")
    if problems:
        raise SpecError(problems)
    return s


def fill(text, params):
    return re.sub(r"\{(\w+)\}", lambda m: str(params.get(m.group(1), m.group(0))), text)


# ---------- flow templates ----------

def template(flow):
    """flows/<name>/template.yaml as a dict, or None. A template is a spec with blanks: `params` maps each parameter
    to a question the orchestrator asks; everything else is the starting spec."""
    f = Path(flow.folder) / "template.yaml" if flow.folder else None
    return load(f.read_text(encoding="utf-8")) if f and f.exists() else None


def from_template(flow, **given):
    """A starting draft from the flow's template: its steps and gates, the params given so far, blanks for the rest."""
    tpl = template(flow) or {"steps": [{"title": "Do the task", "instruction": "{goal}", "tools": list(flow.execute_toolsets)}],
                             "params": {}}
    asks = tpl.get("params") or {}
    spec = {k: copy.deepcopy(v) for k, v in tpl.items() if k != "params"}
    spec["flow"] = flow.name
    spec["params"] = {k: given.get(k, "") for k in asks}
    for k in ("name", "goal", "workspace", "trigger", "tz"):
        if given.get(k):
            spec[k] = given[k]
    return spec, asks


# ---------- when is it due ----------

def next_due(spec, after):
    """Epoch seconds of the next run strictly after `after`, or None (manual, or a one-off already past)."""
    t = spec.get("trigger") or {}
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(spec.get("tz") or DEFAULTS["tz"])
    if t.get("kind") == "now":
        return after
    if t.get("kind") == "at":
        at = datetime.fromisoformat(str(t["at"]))
        at = at if at.tzinfo else at.replace(tzinfo=tz)
        return at.timestamp() if at.timestamp() > after else None
    if t.get("kind") == "cron":
        from croniter import croniter
        return croniter(t["cron"], datetime.fromtimestamp(after, tz)).get_next(datetime).timestamp()
    return None


def describe_trigger(spec):
    t = spec.get("trigger") or {}
    return {"now": "run once, now", "manual": "runs when you start it", "at": f"once at {t.get('at')} ({spec.get('tz')})",
            "cron": f"on '{t.get('cron')}' ({spec.get('tz')})"}.get(t.get("kind"), "?")
