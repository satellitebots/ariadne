"""Phase policy. The phase lives in a file, not an env var, because Hermes may serve the run from a gateway
process that was started by an earlier run."""
import json
import os
import time
from pathlib import Path


def _home():
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def current_phase(home=None):
    try:
        return (Path(home or _home()) / "ariadne_phase").read_text(encoding="utf-8").strip() or "execute"
    except OSError:
        return "execute"


def plan_tools(home=None):
    try:
        data = json.loads((Path(home or _home()) / "ariadne_flow.json").read_text(encoding="utf-8"))
        return list(data.get("plan_tools") or [])
    except (OSError, ValueError):
        return []


def allowed_in_plan(tool_name, allow):
    """Exact name, or an MCP tool whose own name is in the list (Hermes prefixes MCP tools with the server)."""
    name = (tool_name or "").lower()
    for t in allow:
        t = t.lower()
        if name == t or name.endswith("_" + t) or name.endswith(":" + t) or name.endswith("." + t):
            return True
    return False


def decide(tool_name, phase, allow):
    if phase != "plan" or allowed_in_plan(tool_name, allow):
        return None
    return (f"'{tool_name}' is not allowed while planning: this is the read-only plan phase, before sign-off. "
            "Do not try to do the work now. Write it as a step in the plan; it runs after the plan is approved.")


def _log(entry, home=None):
    try:
        logs = Path(home or _home()) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / "ariadne_tools.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def pre_tool_call(tool_name=None, args=None, task_id=None, **kwargs):
    phase = current_phase()
    reason = decide(tool_name, phase, plan_tools())
    _log({"ts": time.time(), "phase": phase, "tool": tool_name, "blocked": bool(reason),
          "args": {k: (str(v)[:200]) for k, v in (args or {}).items()} if isinstance(args, dict) else str(args)[:200]})
    if reason:
        return {"action": "block", "message": reason}
    return None
