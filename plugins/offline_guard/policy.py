"""Tool-call policy: refuse tool calls whose job is to reach outside the machine or the LAN.

Layered on top of config (agent.disabled_toolsets removes web/browser tools from the prompt) and the
socket guard (which cannot see child processes such as curl started by the terminal tool).

Rules, in order:
1. Web and browser tools (web_search, web_extract, browser*) are blocked outright.
2. Any string argument containing a URL whose host is not local is blocked.
3. A networked command (curl, wget, Invoke-WebRequest, pip/npm install, npx, uvx, git clone/fetch/pull/
   push, ssh/scp ...) is blocked unless every URL it names is local. A networked command with no URL at
   all is blocked, because its default target (PyPI, npm, a git remote) is not known to be local.
"""
import re

from .guard import is_local_host

WEB_TOOLS = {"web_search", "web_extract"}
_URL = re.compile(r"\b(?:https?|ftp|wss?|git|ssh)://(?:[^@/\s'\"]+@)?(\[[^\]]+\]|[^:/\s'\"?#]+)", re.I)
_NET_CMD = re.compile(
    r"\b(curl|wget|Invoke-WebRequest|iwr|Invoke-RestMethod|irm|Start-BitsTransfer|ssh|scp|sftp|rsync|ftp|nc|telnet)\b"
    r"|\b(pip3?|uv\s+pip|poetry|pipx)\s+(install|download|add)\b"
    r"|\b(npm|pnpm|yarn|bun)\s+(install|i|add|update|create|dlx)\b|\bnpx\b|\buvx\b|\bdeno\s+run\b"
    r"|\bgit\s+(clone|fetch|pull|push|ls-remote|submodule\s+update)\b"
    r"|\b(apt|apt-get|winget|choco|scoop|brew)\s+(install|upgrade|update)\b",
    re.I)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def decide(tool_name, args):
    """Return None to allow, or a reason string to block."""
    name = (tool_name or "").lower()
    if name in WEB_TOOLS or name.startswith("browser"):
        return f"tool '{tool_name}' reaches the internet and Ariadne runs offline"
    texts = list(_strings(args or {}))
    hosts = [m.group(1).strip("[]") for t in texts for m in _URL.finditer(t)]
    external = sorted({h for h in hosts if not is_local_host(h)})
    if external:
        return f"arguments name non-local host(s) {', '.join(external)}; Ariadne runs offline"
    for t in texts:
        m = _NET_CMD.search(t)
        if m and not hosts:
            return (f"command uses '{m.group(0).strip()}', which needs the network and names no local URL; "
                    "Ariadne runs offline (use a local mirror URL if one exists)")
    return None


def pre_tool_call(tool_name=None, args=None, task_id=None, **kwargs):
    reason = decide(tool_name, args)
    if reason:
        return {"action": "block", "message": f"Blocked by Ariadne offline guard: {reason}."}
    return None
