"""Tool policy for the commander's chair.

The terminal/desktop chat home may talk, ask, and submit tasks. It may not *do* the work: no terminal, no file
writes, no browser, no subagents. Otherwise a capable model reads the request and just executes it - a skill is
advice it can ignore, a refused tool call is not.

MCP tools of the `ariadne_tasks` server are allowed: they are the drill. Read-only memory and clarify are allowed.
"""
import json
import os
import re
import time
from pathlib import Path

# Doing-tools: names that change the machine, act on a page, or spend a model call. Read-only internet is NOT here:
# answering "what is the stock price" is conversation, and a chat that cannot look anything up is not a chat.
DOERS = ("terminal", "shell", "exec", "write_file", "read_file", "list_files", "search_files", "patch",
         "apply_patch", "code_execution", "run_python", "browser", "delegate_task", "spawn",
         "image_gen", "video_gen", "computer", "screenshot", "mouse", "keyboard")

# Allowed by name even though they look like doing-tools; the drill itself is the exception.
SAFE = {"clarify", "skill_view", "skills_list", "memory_recall", "memory_record", "todo", "todo_write",
        "todo_read", "submit_task", "wait_task", "get_task", "list_tasks", "list_sessions", "set_gates",
        "approve_task", "revise_task", "cancel_task", "feedback_task", "get_status", "get_skill", "save_skill"}

MESSAGE = ("This home cannot do the work itself: no terminal, no files, no browser. Submit the task with "
           "submit_task so Ariadne can plan it and the person can sign off. Do not work around this, and do not "
           "paste the result into the chat instead.")


def _is_doer(name: str) -> bool:
    n = (name or "").lower()
    tail = re.split(r"__|\.|:", n)[-1]
    return any(n == d or n.startswith(d) or tail == d or tail.startswith(d) for d in DOERS)


def decide(tool_name, args=None):
    """Return a block reason, or None to allow."""
    name = (tool_name or "").lower()
    if not name:
        return None
    if "ariadne_tasks" in name or "ariadne-tasks" in name:
        return None
    tail = re.split(r"__|\.|:", name)[-1]
    if name in SAFE or tail in SAFE:
        return None
    if _is_doer(name):
        return MESSAGE
    return None


def _log(entry):
    try:
        home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
        logs = Path(home) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / "ariadne_gate.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def pre_tool_call(tool_name=None, args=None, task_id=None, **kwargs):
    reason = decide(tool_name, args)
    _log({"ts": time.time(), "tool": tool_name, "blocked": bool(reason)})
    if reason:
        return {"action": "block", "message": reason}
    return None
