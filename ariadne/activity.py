"""Activity log: one place to see what Ariadne is doing right now.

Everything lands in .ariadne/logs/activity.log:
  - task events (brief, route, plan, checkpoints, steps, QA, KV parking, reports) from the task store
  - every call to Ariadne's MCP servers (tasks, memory, git, diagram, image, text, export): tool, arguments, time
`python -m ariadne watch` follows that file live, merged with the Hermes workers' own tool calls and model calls
(each flow home's logs/agent.log), so you can watch a task step by step.
"""
import functools
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from . import paths

LOG = paths.LOGS / "activity.log"
_lock = threading.Lock()


def log(source, message):
    """Append one line: 'HH:MM:SS [source] message' (first line of the message, capped)."""
    line = str(message).strip().splitlines()[0][:300] if str(message).strip() else ""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with _lock, open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} [{source}] {line}\n")
    except OSError:
        pass


def _short(v, n=80):
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "..."


def instrument(server, name):
    """Make every tool of an MCP server log its calls (name, arguments, duration, result size or error)."""
    original = server.tool

    def tool(*args, **kwargs):
        register = original(*args, **kwargs)

        def wrap(fn):
            @functools.wraps(fn)
            def logged(*a, **k):
                shown = ", ".join([_short(x) for x in a] + [f"{key}={_short(val)}" for key, val in k.items()])
                log(f"mcp:{name}", f"{fn.__name__}({shown})")
                t = time.time()
                try:
                    out = fn(*a, **k)
                except Exception as e:
                    log(f"mcp:{name}", f"{fn.__name__} failed after {time.time() - t:.1f}s: {type(e).__name__}: {e}")
                    raise
                log(f"mcp:{name}", f"{fn.__name__} done in {time.time() - t:.1f}s ({len(str(out))} chars)")
                return out
            return register(logged)
        return wrap

    server.tool = tool
    return server


# ---------- watch ----------

_TOOL = re.compile(r"^\S+ (\d\d:\d\d:\d\d).*agent\.tool_executor: tool (\S+) (completed|failed)\s*\(([^)]*)\)")
_CALL = re.compile(r"^\S+ (\d\d:\d\d:\d\d).*API call #(\d+): model=(\S+).*?in=(\d+) out=(\d+).*?latency=([\d.]+s)"
                   r"(?:.*?cache=(\d+)/(\d+))?")


def _hermes_line(flow, line):
    m = _TOOL.match(line)
    if m:
        return f"{m.group(1)} [{flow}] tool {m.group(2)} {m.group(3)} ({m.group(4)})"
    m = _CALL.match(line)
    if m:
        cache = f", cached {m.group(7)}/{m.group(8)}" if m.group(7) else ""
        return (f"{m.group(1)} [{flow}] model {m.group(3)} call {m.group(2)}: {m.group(4)} tokens in, "
                f"{m.group(5)} out, {m.group(6)}{cache}")
    return None


def _sources():
    out = [("", LOG)]
    for home in sorted(paths.HOMES.glob("*")) if paths.HOMES.exists() else []:
        out.append((home.name, home / "logs" / "agent.log"))
    return out


def watch(history=20, poll=1.0, out=sys.stdout):
    """Follow the activity log and the workers' tool and model calls until Ctrl+C."""
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-history:]:
            print(line, file=out)
    pos = {str(p): (p.stat().st_size if p.exists() else 0) for _, p in _sources()}
    print(f"--- following {LOG} and the flows' Hermes logs (Ctrl+C to stop) ---", file=out, flush=True)
    try:
        while True:
            for flow, p in _sources():
                key = str(p)
                if not p.exists():
                    continue
                size = p.stat().st_size
                start = pos.get(key, 0) if size >= pos.get(key, 0) else 0
                if size == start:
                    pos[key] = size
                    continue
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(start)
                    chunk = f.read()
                    pos[key] = f.tell()
                for line in chunk.splitlines():
                    shown = line if not flow else _hermes_line(flow, line)
                    if shown:
                        print(shown, file=out, flush=True)
            time.sleep(poll)
    except KeyboardInterrupt:
        return 0


def main(argv):
    """python -m ariadne watch [--history N]"""
    n = int(argv[argv.index("--history") + 1]) if "--history" in argv else 20
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    return watch(history=n)
