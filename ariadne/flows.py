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
    "model": {"default": "coder", "provider": "custom", "base_url": paths.LLM_BASE_URL, "context_length": 65536},
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
    model: str = "coder"
    skills: list = field(default_factory=list)
    mcp_servers: list = field(default_factory=list)
    plan_toolsets: list = field(default_factory=lambda: ["file", "skills"])
    execute_toolsets: list = field(default_factory=lambda: ["file", "terminal", "skills", "todo"])
    plan_tools: list = field(default_factory=lambda: list(DEFAULT_PLAN_TOOLS))
    checks: list = field(default_factory=list)
    max_turns: dict = field(default_factory=lambda: {"plan": 20, "execute": 40})
    run_budget: dict = field(default_factory=lambda: {"plan": 900, "execute": 1800})
    folder: Path = None

    @property
    def home(self):
        return paths.HOMES / self.name


def _mcp_registry(flows_dir):
    f = Path(flows_dir) / "mcp_servers.yaml"
    return yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else {}


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
              model=data.get("model", "coder"), skills=list(data.get("skills") or []),
              mcp_servers=list(data.get("mcp_servers") or []),
              plan_toolsets=list(ts.get("plan") or ["file", "skills"]),
              execute_toolsets=list(ts.get("execute") or ["file", "terminal", "skills", "todo"]),
              plan_tools=list(data.get("plan_tools") or DEFAULT_PLAN_TOOLS),
              checks=list(data.get("checks") or []), folder=folder)
    fl.max_turns.update(data.get("max_turns") or {})
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
        return value.replace("{python}", str(paths.PYTHON)).replace("{root}", str(paths.ROOT))
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def compile_flow(fl, flows_dir=None):
    """Write the flow's Hermes home. Safe to re-run; returns the home path."""
    registry = _mcp_registry(flows_dir or fl.folder.parent)
    home = fl.home
    home.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(json.dumps(BASE_CONFIG))
    cfg["model"]["default"] = fl.model
    cfg["mcp_servers"] = {m: _expand(registry[m]) for m in fl.mcp_servers}
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
    (home / "ariadne_flow.json").write_text(json.dumps(
        {"flow": fl.name, "plan_tools": fl.plan_tools}, indent=2), encoding="utf-8")
    return home


def compile_all(flows_dir=None):
    return {name: compile_flow(fl, flows_dir) for name, fl in load_flows(flows_dir).items()}


if __name__ == "__main__":  # python -m ariadne.flows  -> validate and compile every flow
    for name, home in compile_all().items():
        print(f"{name}: {home}")
