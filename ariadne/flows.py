"""Flows: one folder per kind of work (flows/<name>/flow.yaml + optional skills/). Users add a flow by adding a folder.

A flow decides, for every task routed to it: the model, the skills, the MCP servers, which toolsets each phase
gets, and which tools the read-only plan phase may call. compile_flow() turns a flow into a Hermes home
(.ariadne/homes/<flow>/) - the "Hermes worker, set up by the chosen flow" - without touching upstream Hermes.
"""
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import yamlio as yaml

from . import paths

DEFAULT_PLAN_TOOLS = ["read_file", "search_files", "skill_view", "skills_list", "todo",
                      "memory_recall", "git_status", "git_diff", "git_log", "git_show"]

# Settings every worker home gets (local models only; quiet, no background fetches). Mirrors profiles\llamaswap.
BASE_CONFIG = {
    "_config_version": 12,  # current upstream schema; without it Hermes warns that it cannot migrate the file
    "model": {"default": "qwen3.5-9b", "provider": "custom", "base_url": paths.LLM_BASE_URL, "context_length": 65536},
    "model_catalog": {"enabled": False},
    "models_dev": {"url": "http://127.0.0.1:9/models-dev-disabled.json"},
    "updates": {"check": False},
    "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
    "fallback_providers": [{"provider": "custom", "model": "ariadne-qwen3.5-4b",
                            "base_url": "http://localhost:11434/v1"}],
}


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
    requires: list = field(default_factory=list)   # system tools the flow's MCP servers need (deps.SYSTEM_TOOLS, chrome)
    real_logins: bool = True          # browser: use the person's real Chrome profile (logins) unless a flow turns it off
    blocklist: list = field(default_factory=list)   # network: hosts this flow may not reach (everything else allowed)
    max_iterations: int = 10      # execute -> QA rounds at most; stops earlier when it stops making progress
    max_turns: dict = field(default_factory=lambda: {"plan": 20, "execute": 40, "review:plan": 15})
    run_budget: dict = field(default_factory=lambda: {"plan": 900, "execute": 1800})
    folder: Path = None

    @property
    def shared_skills(self):
        """The flow's shared skills: skills/<flow>/<name>/SKILL.md in the repo (written by the larger models that
        drive Ariadne, or contributed), loaded in every run of the flow."""
        d = paths.ROOT / "skills" / self.name
        return sorted(p.parent.name for p in d.glob("*/SKILL.md")) if d.exists() else []

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
    ts = data.get("toolsets") or {}
    fl = Flow(name=data["name"], description=data["description"].strip(), when=data["when"].strip(),
              model=data.get("model", "qwen3.5-9b"), execute_model=str(data.get("execute_model") or ""),
              status=str(data.get("status") or "beta"),
              skills=list(data.get("skills") or []),
              mcp_servers=list(data.get("mcp_servers") or []),
              plan_toolsets=list(ts.get("plan") or ["file", "skills"]),
              execute_toolsets=list(ts.get("execute") or ["file", "terminal", "skills", "todo"]),
              plan_tools=list(data.get("plan_tools") or DEFAULT_PLAN_TOOLS),
              checks=list(data.get("checks") or []), folder=folder,
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
    for s in fl.skills:
        if not (folder / "skills" / s / "SKILL.md").exists():
            raise FlowError(f"{fl.name}: skill '{s}' has no skills/{s}/SKILL.md")
    return fl


def load_flows(flows_dir=None):
    flows_dir = Path(flows_dir or paths.FLOWS_DIR)
    out = {}
    for d in sorted(p for p in flows_dir.iterdir() if (p / "flow.yaml").exists()):
        fl = load_flow(d)
        out[fl.name] = fl
    registry = _mcp_registry(flows_dir)
    for fl in out.values():
        missing = [m for m in fl.mcp_servers if m not in registry]
        if missing:
            raise FlowError(f"{fl.name}: unknown MCP server(s) {missing}; define them in flows/mcp_servers.yaml")
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
    extra = when.get("real_logins" if fl.real_logins else "isolated") or []
    if extra:
        entry["args"] = list(entry.get("args") or []) + list(extra)
    return _expand(entry)


def compile_flow(fl, flows_dir=None):
    """Write the flow's Hermes home. Safe to re-run; returns the home path."""
    registry = _mcp_registry(flows_dir or fl.folder.parent)
    home = fl.home
    home.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(json.dumps(BASE_CONFIG))
    cfg["model"]["default"] = fl.model
    from . import models as modellib
    ctx = modellib.load().context
    cfg["model"]["context_length"] = ctx["window"]
    # Context compression (Hermes's own compressor): past compress_at tokens the run pauses, the same model
    # summarises the older turns (auxiliary "auto" = the main model, so nothing swaps), the recent tail stays.
    cfg["compression"] = {"enabled": True, "threshold": 0.75, "threshold_tokens": ctx["compress_at"],
                          "max_attempts": 4, "tail_mode": "lean"}
    cfg["auxiliary"] = {"compression": {"provider": "auto", "model": "", "base_url": "", "api_key": "",
                                        "timeout": 900, "extra_body": {}, "reasoning_effort": ""},
                        # No model call for session titles: it would overwrite the KV slot that is parked after the run.
                        "title_generation": {"enabled": True, "model_upgrade_enabled": False, "provider": "auto",
                                             "model": "", "prefer_fast_model": False, "extra_body": {}}}
    cfg["mcp_servers"] = {m: _server_config(registry[m], fl) for m in fl.mcp_servers}
    cfg["plugins"] = {"auto_update_check_hours": 0, "enabled": ["ariadne_phase"]}
    (home / "config.yaml").write_text("# Generated by ariadne.flows from flows/%s - do not edit.\n%s"
                                      % (fl.name, yaml.safe_dump(cfg, sort_keys=False)), encoding="utf-8")
    # The phase plugin (plan = read-only allowlist) and the flow's skills.
    plug_src, plug_dst = paths.PLUGINS_DIR / "ariadne_phase", home / "plugins" / "ariadne_phase"
    if plug_dst.exists():
        shutil.rmtree(plug_dst)
    shutil.copytree(plug_src, plug_dst, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    for s in fl.skills:
        dst = home / "skills" / s
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(fl.folder / "skills" / s, dst)
    install_shared_skills(fl)
    (home / "ariadne_flow.json").write_text(json.dumps(
        {"flow": fl.name, "plan_tools": fl.plan_tools, "blocklist": fl.blocklist}, indent=2), encoding="utf-8")
    return home


def install_shared_skills(fl):
    """Copy the flow's shared skills (skills/<flow>/*) into its Hermes home."""
    for name in fl.shared_skills:
        src = paths.ROOT / "skills" / fl.name / name
        dst = fl.home / "skills" / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


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


def compile_all(flows_dir=None):
    return {name: compile_flow(fl, flows_dir) for name, fl in load_flows(flows_dir).items()}


if __name__ == "__main__":  # python -m ariadne.flows  -> validate and compile every flow
    for name, home in compile_all().items():
        print(f"{name}: {home}")
