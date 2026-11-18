"""Activity log: everything Ariadne does, in one place.

Always written to a log file - .ariadne/logs/activity-YYYY-MM-DD.log, one file per day, the two newest kept
(older ones are deleted, so at most ~48 hours are on disk):
  - task events (brief, gates, route, plan, checkpoints, steps, QA, KV parking, reports)
  - every call to Ariadne's MCP servers (tasks, memory, git, diagram, image, text, export): tool, arguments, time

`python -m ariadne watch` shows it live in a terminal, merged with the worker's output, the model server's log, and
each Hermes worker's tool calls, model calls (tokens, latency, cache hits), warnings and errors.
`--watch` on any command opens that in its own terminal window; `python -m ariadne watch --always` makes every
run open it (settings in .ariadne/settings.json; `--never` turns it off).
"""
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from . import paths

LOG_DIR = paths.LOGS
KEEP_DAYS = 2
SETTINGS = paths.STATE / "settings.json"
WATCH_PID = paths.STATE / "watch.pid"
_lock = threading.Lock()


def log_file(day=None):
    return LOG_DIR / f"activity-{day or time.strftime('%Y-%m-%d')}.log"


def _prune():
    files = sorted(LOG_DIR.glob("activity-*.log"))
    for f in files[:-KEEP_DAYS]:
        try:
            f.unlink()
        except OSError:
            pass


def log(source, message):
    """Append one line: 'HH:MM:SS [source] message' (first line of the message, capped) to today's file."""
    line = str(message).strip().splitlines()[0][:300] if str(message).strip() else ""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        f = log_file()
        new_day = not f.exists()
        with _lock, open(f, "a", encoding="utf-8") as out:
            out.write(f"{time.strftime('%H:%M:%S')} [{source}] {line}\n")
        if new_day:
            _prune()
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


# ---------- settings and the terminal window ----------

def settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_setting(key, value):
    s = settings()
    s[key] = value
    paths.ensure()
    SETTINGS.write_text(json.dumps(s, indent=1), encoding="utf-8")


def _alive(pid):
    if not pid:
        return False
    if paths.WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def open_window():
    """Open a terminal window running `python -m ariadne watch` (once; reuses an open one)."""
    try:
        if _alive(int(WATCH_PID.read_text().strip())):
            return False
    except (OSError, ValueError):
        pass
    py, root = str(paths.VENV_PY if paths.VENV_PY.exists() else sys.executable), str(paths.ROOT)
    env = dict(os.environ, PYTHONPATH=root, PYTHONIOENCODING="utf-8")
    watch = [py, "-m", "ariadne", "watch", "--history", "40"]
    if paths.WINDOWS:
        p = subprocess.Popen(["powershell", "-NoExit", "-Command",
                              f"$host.UI.RawUI.WindowTitle = 'Ariadne activity'; & '{py}' -m ariadne watch --history 40"],
                             cwd=root, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
    elif sys.platform == "darwin":
        cmd = f"cd '{root}' && PYTHONPATH='{root}' '{py}' -m ariadne watch --history 40"
        p = subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{cmd}"'])
    else:
        term = next((t for t in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm") if shutil.which(t)), None)
        if not term:
            print("no terminal emulator found; run: python -m ariadne watch", flush=True)
            return False
        p = subprocess.Popen([term, "--", *watch] if term == "gnome-terminal" else [term, "-e", " ".join(watch)],
                             cwd=root, env=env)
    WATCH_PID.write_text(str(p.pid))
    return True


def maybe_open_window():
    """Open the activity window if the person asked for it on every run."""
    if settings().get("watch_window"):
        try:
            open_window()
        except OSError as e:
            print(f"could not open the activity window: {e}", flush=True)


# ---------- watch ----------

_TOOL = re.compile(r"^\S+ (\d\d:\d\d:\d\d).*agent\.tool_executor: tool (\S+) (completed|failed)\s*\(([^)]*)\)")
_CALL = re.compile(r"^\S+ (\d\d:\d\d:\d\d).*API call #(\d+): model=(\S+).*?in=(\d+) out=(\d+).*?latency=([\d.]+s)"
                   r"(?:.*?cache=(\d+)/(\d+))?")
_WARN = re.compile(r"^\S+ (\d\d:\d\d:\d\d)\S* (WARNING|ERROR|CRITICAL) (.*)$")


def _hermes_line(flow, line):
    m = _TOOL.match(line)
    if m:
        return f"{m.group(1)} [{flow}] tool {m.group(2)} {m.group(3)} ({m.group(4)})"
    m = _CALL.match(line)
    if m:
        cache = f", cached {m.group(7)}/{m.group(8)}" if m.group(7) else ""
        return (f"{m.group(1)} [{flow}] model {m.group(3)} call {m.group(2)}: {m.group(4)} tokens in, "
                f"{m.group(5)} out, {m.group(6)}{cache}")
    m = _WARN.match(line)
    if m:
        return f"{m.group(1)} [{flow}] {m.group(2).lower()}: {m.group(3)[:240]}"
    return None


def _plain(tag):
    return lambda line: f"{time.strftime('%H:%M:%S')} [{tag}] {line}" if line.strip() else None


def _sources():
    out = [(lambda line: line, log_file()), (_plain("worker"), LOG_DIR / "worker.log"),
           (_plain("models"), LOG_DIR / "llama-swap.log")]
    for home in sorted(paths.HOMES.glob("*")) if paths.HOMES.exists() else []:
        out.append((functools.partial(_hermes_line, home.name), home / "logs" / "agent.log"))
    return out


def _tail(path, max_bytes=200_000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - max_bytes))
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def recent(n=12):
    """The last n activity lines across every source, oldest first (for status panels)."""
    lines, today = [], time.strftime("%Y-%m-%d")
    for fmt, path in _sources():
        if path.name in ("worker.log", "llama-swap.log"):
            continue  # untimestamped sources: only meaningful when followed live
        for line in _tail(path):
            if re.match(r"\d{4}-\d\d-\d\d ", line) and not line.startswith(today):
                continue  # Hermes logs carry the date; formatted lines keep only the time, so keep today's
            s = fmt(line)
            if s:
                lines.append(s)
    lines.sort(key=lambda s: s[:8])  # every formatted line starts HH:MM:SS
    return lines[-n:]


def _keys_available():
    return os.name == "nt" and sys.stdin is not None and sys.stdin.isatty()


def _key():
    """One pending keypress, lowercased ('' if none). Windows console only."""
    import msvcrt
    if not msvcrt.kbhit():
        return ""
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):  # arrow/function keys come as two codes
        msvcrt.getwch()
        return ""
    return ch.lower()


def watch(history=20, poll=1.0, out=sys.stdout, rounds=None):
    """Follow everything until Ctrl+C (rounds: stop after that many polls, for tests)."""
    today = log_file()
    if today.exists():
        for line in today.read_text(encoding="utf-8", errors="replace").splitlines()[-history:]:
            print(line, file=out)
    pos = {str(p): (p.stat().st_size if p.exists() else 0) for _, p in _sources()}
    keys = _keys_available() and out is sys.stdout
    print("--- following Ariadne's activity, worker, model server and Hermes logs ---", file=out)
    print("    keys: [P] park the running task  [R] resume it  [S] stop Ariadne (worker + models)  [Q] close"
          if keys else "    Ctrl+C closes this; `python -m ariadne stop` stops Ariadne", file=out, flush=True)
    n, confirm_stop = 0, False
    try:
        while rounds is None or n < rounds:
            n += 1
            k = _key() if keys else ""
            if k == "q":
                break
            if k == "p":
                from . import park
                park.request("watch window")
                print("park requested: the task stops at its next step boundary", file=out, flush=True)
            elif k == "r":
                from . import park
                park.resume()
                print("resumed", file=out, flush=True)
            elif k == "s":
                confirm_stop = True
                print("stop Ariadne? The running task goes back to you (work kept). [Y] yes, any other key no",
                      file=out, flush=True)
                continue
            elif confirm_stop:
                confirm_stop = False
                if k == "y":
                    from .orchestrator import stop_all
                    stopped = stop_all("stopped from the watch window")
                    print(f"Ariadne stopped (tasks back to you: {', '.join(stopped) or 'none'}). "
                          "Start again with any task command, or `python -m ariadne serve`.", file=out, flush=True)
                else:
                    print("not stopped", file=out, flush=True)
            for fmt, p in _sources():
                key = str(p)
                if not p.exists():
                    continue
                size, start = p.stat().st_size, pos.get(key, 0)
                if size < start:
                    start = 0  # rotated or truncated
                if size == start:
                    pos[key] = size
                    continue
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(start)
                    chunk = f.read()
                    pos[key] = f.tell()
                for line in chunk.splitlines():
                    shown = fmt(line)
                    if shown:
                        print(shown, file=out, flush=True)
            time.sleep(poll)
    except KeyboardInterrupt:
        pass
    return 0


def main(argv):
    """python -m ariadne watch [--history N] [--open] [--always | --never]"""
    if "--always" in argv or "--never" in argv:
        set_setting("watch_window", "--always" in argv)
        print("every run opens the activity window" if "--always" in argv else "activity window only on --watch")
        if "--never" in argv:
            return 0
        argv = ["--open"]
    if "--open" in argv:
        print("activity window opened" if open_window() else "activity window already open")
        return 0
    n = int(argv[argv.index("--history") + 1]) if "--history" in argv else 20
    return watch(history=n)
