"""Flows: one folder per kind of work (flows/<name>/flow.yaml + optional skills/). Users add a flow by adding a folder.

A flow decides, for every task routed to it: the model, the skills, the MCP servers, which toolsets each phase
gets, and which tools the read-only plan phase may call. The runtime reads the flow directly (mcp_server_config,
shared_skill_dirs, plan_tools); prepare_homes() only creates the per-flow home the runtime keeps its sessions and
markers in.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import yamlio as yaml

from . import paths

DEFAULT_PLAN_TOOLS = ["read_file", "search_files", "skill_view", "skills_list", "todo",
                      "memory_recall", "git_status", "git_diff", "git_log", "git_show"]

# Every key flows/<name>/flow.yaml may carry. Anything else is a typo and is refused (see load_flow).
FLOW_KEYS = {"name", "description", "when", "model", "execute_model", "reasoning", "status", "skills",
             "mcp_servers", "toolsets", "plan_tools", "checks", "requires", "browser", "network",
             "max_turns", "max_iterations", "run_budget", "task_budget"}

class FlowError(ValueError):
    pass


@dataclass
class Flow:
    name: str
    description: str
    when: str
    model: str = "qwen3.5-9b"   # agent model (serving/models.yaml) that plans; also runs steps unless execute_model is set
    execute_model: str = ""     # agent model for steps that name none (e.g. a fast MoE while a dense model plans)
    reasoning: dict = field(default_factory=lambda: {"execute": "low"})   # Hermes --reasoning per phase ('' = default)
    status: str = "beta"        # beta (validated) or experimental (shipped, not yet validated)
    skills: list = field(default_factory=list)
    mcp_servers: list = field(default_factory=list)
    plan_toolsets: list = field(default_factory=lambda: ["file", "skills"])
    execute_toolsets: list = field(default_factory=lambda: ["file", "terminal", "skills", "todo"])
    plan_tools: list = field(default_factory=lambda: list(DEFAULT_PLAN_TOOLS))
    checks: list = field(default_factory=list)
    brief: str = ""            # flows/<name>/FLOW.md: the coordination the planner must follow
    requires: list = field(default_factory=list)   # system tools the flow's MCP servers need (deps.SYSTEM_TOOLS, chrome)
    real_logins: bool = True          # browser: use the person's real Chrome profile (logins) unless a flow turns it off
    blocklist: list = field(default_factory=list)   # network: hosts this flow may not reach (everything else allowed)
    max_iterations: int = 10      # execute -> QA rounds at most; stops earlier when it stops making progress
    max_turns: dict = field(default_factory=lambda: {"plan": 20, "execute": 40, "review:plan": 15})
    run_budget: dict = field(default_factory=lambda: {"plan": 900, "execute": 1800})
    task_budget: int = 0          # the task's wall clock, in seconds of worker time (0 = no task-level limit)
    folder: Path = None

    @property
    def shared_skills(self):
        """The flow's shared skills: skills/<flow>/<name>/SKILL.md in the repo (written by the larger models that
        drive Ariadne, or contributed), loaded in every run of the flow."""
        return sorted(shared_skill_dirs(self.name))

    @property
    def step_model(self):
        return self.execute_model or self.model

    @property
    def home(self):
        return paths.HOMES / self.name


def _mcp_registry(flows_dir):
    """flows/mcp_servers.yaml; a flows folder elsewhere (tests) falls back to its parent's."""
    for d in (Path(flows_dir), Path(flows_dir).parent):
        f = d / "mcp_servers.yaml"
        if f.exists():
            return yaml.safe_load(f.read_text(encoding="utf-8"))
    return {}


def load_flow(folder):
    folder = Path(folder)
    data = yaml.safe_load((folder / "flow.yaml").read_text(encoding="utf-8")) or {}
    for key in ("name", "description", "when"):
        if not str(data.get(key) or "").strip():
            raise FlowError(f"{folder.name}/flow.yaml: '{key}' is required")
    if data["name"] != folder.name:
        raise FlowError(f"{folder.name}/flow.yaml: name '{data['name']}' must match its folder")
    # Unknown keys are refused, not ignored: a typo ('max_turn' for 'max_turns') would otherwise keep the default
    # silently, and the whole point of a flow folder is that its file says what happens.
    unknown = sorted(set(data) - FLOW_KEYS)
    if unknown:
        raise FlowError(f"{folder.name}/flow.yaml: unknown key(s) {unknown}; known keys: {sorted(FLOW_KEYS)}")
    for section, allowed in (("toolsets", {"plan", "execute"}), ("browser", {"real_logins"}),
                             ("network", {"blocklist"})):
        extra = sorted(set(data.get(section) or {}) - allowed)
        if extra:
            raise FlowError(f"{folder.name}/flow.yaml: unknown key(s) {extra} under '{section}'; "
                            f"known: {sorted(allowed)}")
    ts = data.get("toolsets") or {}
    brief_file = folder / "FLOW.md"
    brief = brief_file.read_text(encoding="utf-8").strip() if brief_file.exists() else ""
    fl = Flow(name=data["name"], description=data["description"].strip(), when=data["when"].strip(),
              model=data.get("model", "qwen3.5-9b"), execute_model=str(data.get("execute_model") or ""),
              status=str(data.get("status") or "beta"),
              skills=list(data.get("skills") or []),
              mcp_servers=list(data.get("mcp_servers") or []),
              plan_toolsets=list(ts.get("plan") or ["file", "skills"]),
              execute_toolsets=list(ts.get("execute") or ["file", "terminal", "skills", "todo"]),
              plan_tools=list(data.get("plan_tools") or DEFAULT_PLAN_TOOLS),
              checks=list(data.get("checks") or []), brief=brief, folder=folder,
              requires=[str(x).lower() for x in data.get("requires") or []],
              real_logins=bool((data.get("browser") or {}).get("real_logins", True)),
              blocklist=[str(h).strip().lower() for h in (data.get("network") or {}).get("blocklist") or []])
    from . import models as modellib
    fl.reasoning.update(data.get("reasoning") or {})
    for key in ("model", "execute_model"):
        name = getattr(fl, key)
        if not name:
            continue
        try:
            agent = modellib.load().get(name)
        except modellib.ModelError as e:
            raise FlowError(f"{fl.name}: {key}: {e}")
        if agent.kind != "agent":
            raise FlowError(f"{fl.name}: {key} '{name}' is a {agent.kind} model; it must be an agent model")
    fl.max_turns.update(data.get("max_turns") or {})
    fl.max_iterations = int(data.get("max_iterations") or fl.max_iterations)
    fl.run_budget.update(data.get("run_budget") or {})
    fl.task_budget = int(data.get("task_budget") or 0)
    for s in fl.skills:
        if not (folder / "skills" / s / "SKILL.md").exists():
            raise FlowError(f"{fl.name}: skill '{s}' has no skills/{s}/SKILL.md")
    return fl


def _approved_flows(flows_dir):
    """flows/flows.yaml: the closed set of flows a task may belong to (None when there is no manifest)."""
    f = Path(flows_dir) / "flows.yaml"
    if not f.exists():
        return None
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    names = [str(n).strip() for n in (data.get("approved") or []) if str(n).strip()]
    return names or None


def _approved_tools(flows_dir):
    """flows/tools.yaml: the closed set of MCP servers and system tools a flow may use."""
    f = Path(flows_dir) / "tools.yaml"
    if not f.exists():
        return None, {}
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    approved = data.get("approved") or {}
    return (set(approved.get("mcp") or []), set(approved.get("system") or [])), (data.get("install") or {})


def install_hint(name: str, flows_dir=None) -> str:
    """The command the backbrief should name for a missing system tool."""
    _sets, hints = _approved_tools(flows_dir or paths.FLOWS_DIR)
    return str(hints.get(name) or "python -m ariadne install --system")


def load_flows(flows_dir=None):
    flows_dir = Path(flows_dir or paths.FLOWS_DIR)
    approved = _approved_flows(flows_dir)
    out = {}
    for d in sorted(p for p in flows_dir.iterdir() if (p / "flow.yaml").exists()):
        fl = load_flow(d)
        if approved is not None and fl.name not in approved:
            raise FlowError(f"{fl.name}: not an approved flow; flows/flows.yaml approves {approved}")
        out[fl.name] = fl
    if approved is not None:
        missing = [n for n in approved if n not in out]
        if missing:
            raise FlowError(f"flows/flows.yaml approves {missing}, which have no flows/<name>/flow.yaml")
    registry = _mcp_registry(flows_dir)
    for fl in out.values():
        missing = [m for m in fl.mcp_servers if m not in registry]
        if missing:
            raise FlowError(f"{fl.name}: unknown MCP server(s) {missing}; define them in flows/mcp_servers.yaml")
    tool_sets, _hints = _approved_tools(flows_dir)
    if tool_sets is not None:
        mcp_ok, system_ok = tool_sets
        for fl in out.values():
            bad = [m for m in fl.mcp_servers if m not in mcp_ok]
            if bad:
                raise FlowError(f"{fl.name}: MCP server(s) {bad} are not approved; flows/tools.yaml approves "
                                f"{sorted(mcp_ok)}")
            bad = [r for r in fl.requires if r not in system_ok]
            if bad:
                raise FlowError(f"{fl.name}: system tool(s) {bad} are not approved; flows/tools.yaml approves "
                                f"{sorted(system_ok)}")
    if not out:
        raise FlowError(f"no flows in {flows_dir}")
    return out


def _expand(value):
    if isinstance(value, str):
        return (value.replace("{python}", str(paths.VENV_PY if paths.VENV_PY.exists() else paths.PYTHON))
                .replace("{root}", str(paths.ROOT)).replace("{npx}", paths.npx()))
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def _server_config(entry, fl):
    """A registry entry for this flow: `args_when` adds args by the flow's browser setting
    (real_logins / isolated), so one browser server serves flows with and without the person's logins."""
    entry = dict(entry)
    when = entry.pop("args_when", None) or {}
    from .browser import real_logins
    extra = when.get("real_logins" if real_logins(fl) else "isolated") or []
    if extra:
        entry["args"] = list(entry.get("args") or []) + list(extra)
    return json.loads(json.dumps(_expand(entry)).replace("{home}", fl.home.as_posix()))  # {home}: this flow's home


def mcp_server_config(fl, flows_dir=None):
    """The flow's MCP servers as {server_name: config}, the shape the runtime's Pool takes: registry lookup,
    {python}/{root}/{home}/{npx} expansion, and the browser args the flow's setting asks for."""
    if not fl.mcp_servers:
        return {}
    registry = _mcp_registry(flows_dir or (fl.folder.parent if fl.folder else paths.FLOWS_DIR))
    return {m: _server_config(registry[m], fl) for m in fl.mcp_servers}


COMMON_SKILLS = "common"   # skills/common/*: how to work in Ariadne at all, loaded by every flow


def shared_skill_dirs(flow):
    """{name: folder} of the skills a flow loads: skills/common/* then skills/<flow>/* (the flow's own wins)."""
    out = {}
    for group in (COMMON_SKILLS, flow):
        d = paths.ROOT / "skills" / group
        for p in sorted(d.glob("*/SKILL.md")) if d.exists() else []:
            out[p.parent.name] = p.parent
    return out


def missing_requirements(fl):
    """The flow's `requires` that this machine lacks (empty = ready)."""
    from . import deps
    out = []
    for r in fl.requires:
        if r == "chrome":
            ok = bool(deps.chrome_path())
        elif r in deps.SYSTEM_TOOLS:
            ok = deps.has_tool(r)
        else:
            ok = bool(__import__("shutil").which(r))
        if not ok:
            out.append(r)
    return out


def prepare_homes(flows_dir=None):
    """Create each flow's home (.ariadne/homes/<flow>) - where the runtime keeps sessions, logs and the MCP markers -
    and return {name: home}. Nothing is generated: the runtime reads the flow itself."""
    out = {}
    for name, fl in load_flows(flows_dir).items():
        fl.home.mkdir(parents=True, exist_ok=True)
        out[name] = fl.home
    return out


if __name__ == "__main__":  # python -m ariadne.flows  -> validate and compile every flow
    for name, home in prepare_homes().items():
        print(f"{name}: {home}")
