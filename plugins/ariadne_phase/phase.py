"""Phase policy and the flow's network blocklist. Both live in files in the worker home, not env vars, because
Hermes may serve the run from a gateway process that was started by an earlier run."""
import json
import os
import re
import time
from pathlib import Path


def _home():
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def current_phase(home=None):
    try:
        return (Path(home or _home()) / "ariadne_phase").read_text(encoding="utf-8").strip() or "execute"
    except OSError:
        return "execute"


def _flow(home=None):
    try:
        return json.loads((Path(home or _home()) / "ariadne_flow.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def plan_tools(home=None):
    return list(_flow(home).get("plan_tools") or [])


def blocklist(home=None):
    return [h for h in (_flow(home).get("blocklist") or []) if h]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def blocked_host(args, blocked):
    """The first blocked host named anywhere in the tool's arguments (a URL, a command, a bare domain), or None.
    A blocked entry covers its subdomains: 'example.com' also blocks 'www.example.com'."""
    for text in _strings(args or {}):
        low = text.lower()
        for b in blocked:
            if re.search(r"(?<![\w.-])(?:[\w-]+\.)*" + re.escape(b.lower()) + r"(?![\w-])", low):
                return b
    return None


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
    host = blocked_host(args, blocklist())
    if host and not reason:
        reason = f"'{host}' is on this flow's network blocklist (flow.yaml network.blocklist); do not use it."
    _log({"ts": time.time(), "phase": phase, "tool": tool_name, "blocked": bool(reason),
          "args": {k: (str(v)[:200]) for k, v in (args or {}).items()} if isinstance(args, dict) else str(args)[:200]})
    if reason:
        return {"action": "block", "message": reason}
    return None
