"""Ariadne command line (Windows, Linux, macOS):  ariadne <command>   (or: python -m ariadne <command>)

Tasks and runs (the same verbs as the UI, the chat and MCP - docs/DESIGN.md):
  (no command)               what is going on: the machine, live runs, open drafts, tasks
  chat                       talk with the orchestrator: define tasks, start, park, steer and resume runs
  draft "what you want" --flow F    open a draft from a flow template, then talk it through with `say`
  say DRAFT "message"        one turn with the orchestrator about a draft
  sign DRAFT                 sign a draft: it becomes a task version (and runs now if its trigger says so)
  define FILE.yaml           a whole task definition from a file, as a draft to sign
  tasks | task NAME          signed tasks; one task's definition and runs
  run NAME                   run a task now          schedule NAME "0 7 * * 1-5"|manual|2026-11-25T07:00
  runs [NAME] | run_show RUN the runs; one run's steps, checks and events
  park RUN | steer RUN "note" | resume RUN | cancel RUN     steer a live run: park, steer, resume
  machine                    who holds the GPU, who waits
  flows                      the task templates and what they ask for

Machine and setup:
  doctor | install [--system] [--models] | models [list|index|install NAME...] | resources [max|shared|light]
  ui [--port N] [--bind HOST]   the console in a browser     up [--lan] | down | connect | token   the MCP endpoint
  watch [--open|--always|--never]   live activity            stop [--hard]   stop Ariadne on purpose
  kv [list|drop REF] | browser [status|debug on|off] | casestudy export WS NAME | server | watchdog | local-only
"""
import json
import os
import sys
import time
from pathlib import Path

from . import deps, paths

ALIASES = {"park": "park_run", "show": "run_show"}


def _project_venv():
    exe = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    p = paths.ROOT / ".venv" / exe
    return p if p.exists() else None


def _ensure_project_interpreter(argv):
    """A system-python `ariadne` shim must not run the app: re-exec once in the project venv."""
    if os.environ.get("ARIADNE_REEXEC") or not argv or argv[0] == "install":
        return
    venv = _project_venv()
    if venv is None:
        return
    try:
        if Path(sys.executable).resolve() == venv.resolve():
            return
        os.environ["ARIADNE_REEXEC"] = "1"
        os.execv(str(venv), [str(venv), "-m", "ariadne", *argv])
    except OSError:
        pass


def _when(ts):
    import time
    return time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "-"


def overview():
    from . import verbs
    m = verbs.call("machine")
    print(f"machine: {m['summary']}")
    live = verbs.call("runs", live=True)
    print(f"\nLIVE RUNS ({len(live)})")
    for r in live:
        print(f"  {r['id']}  {r['status']:<8} {r['task']:<24} step {r['step']}/{r['steps_total']}")
    drafts = verbs.call("drafts")
    print(f"\nOPEN DRAFTS ({len(drafts)})")
    for d in drafts:
        name = d["spec"].get("name") or "(no name yet)"
        print(f"  {d['id']}  {d['flow']:<13} {name:<24} {'ready to sign' if d['ready'] else str(len(d['problems'])) + ' to fill in'}")
    tasks = verbs.call("tasks")
    print(f"\nTASKS ({len(tasks)})")
    for t in tasks:
        print(f"  {t['name']:<24} v{t['version']:<3} {t['trigger']:<34} next {_when(t['next_due'])}")
    print("\nariadne chat   - talk it through with the orchestrator")
    return 0


def _print(out):
    if isinstance(out, dict) and "yaml" in out and "problems" in out:          # a draft
        print(out["yaml"])
        if out.get("reply"):
            print(f"orchestrator: {out['reply']}\n")
        print("ready to sign: ariadne sign " + out["id"] if out["ready"] else
              "still missing:\n  - " + "\n  - ".join(out["problems"]))
    elif isinstance(out, list) and out and isinstance(out[0], dict) and "steps_total" in out[0]:
        for r in out:
            print(f"{r['id']}  {r['status']:<10} {r['task']:<24} step {r['step']}/{r['steps_total']}  "
                  f"{_when(r['created'])}  {r['trigger']}")
    elif isinstance(out, list) and out and isinstance(out[0], dict) and "trigger" in out[0] and "version" in out[0]:
        for t in out:
            print(f"{t['name']:<24} v{t['version']:<3} {t['trigger']:<34} last {t['last_run'] or '-'}")
    else:
        print(json.dumps(out, indent=1, ensure_ascii=False, default=str))


def verb_cli(name, rest):
    """`ariadne <verb> positional... --key value`: positionals fill the verb's required arguments in order."""
    from . import verbs
    v = verbs.VERBS[name]
    args, pos, i = {}, [], 0
    while i < len(rest):
        a = rest[i]
        if a.startswith("--"):
            key = a[2:].replace("-", "_")
            if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
                args[key], i = rest[i + 1], i + 2
            else:
                args[key], i = "true", i + 1
        else:
            pos.append(a)
            i += 1
    order = [n for n in v.params if n not in args]
    for n, val in zip(order, pos):
        args[n] = val
    if name == "define" and "yaml" in args and Path(args["yaml"]).exists():
        args["yaml"] = Path(args["yaml"]).read_text(encoding="utf-8")
    for n, (ann, _) in v.params.items():
        if n in args and ann is bool:
            args[n] = str(args[n]).lower() in ("1", "true", "yes")
        elif n in args and ann is int:
            args[n] = int(args[n])
        elif n in args and ann is float:
            args[n] = float(args[n])
    try:
        out = verbs.call(name, **args)
    except verbs.VerbError as e:
        print(str(e))
        return 2
    if name in ("run", "rerun", "sign", "schedule", "resume"):
        from .daemon import ensure_worker
        ensure_worker()
    _print(out)
    return 0


CHAT_COMMANDS = {
    "/status": "what holds the machine and every live run",
    "/park": "[run] stop the live run at its next tool call and free the machine",
    "/resume": "[run] continue a parked run",
    "/steer": "[run] <note> leave a note it reads at its next boundary",
    "/approve": "[run] yes to what a run is asking",
    "/reject": "[run] [why] no to what a run is asking",
    "/cancel": "[run] cancel a run",
}


def _live_runs():
    from . import verbs
    return verbs.call("runs", live=True)


def _pick_run(words):
    """The run a command names, else the only live run (the newest if several, said so)."""
    live = _live_runs()
    if words and (words[0].startswith("r1") or any(r["id"] == words[0] for r in live)):
        return words[0], words[1:]
    if not live:
        raise ValueError("no run is live; name one (`/park r...`)")
    return live[0]["id"], words


def chat_command(line):
    """Commands the terminal chat runs itself: they never wait for the machine or the model."""
    from . import verbs
    word, *rest = line.split()
    if word in ("/help", "/?"):
        return "\n".join(f"  {k:<9} {v}" for k, v in CHAT_COMMANDS.items())
    if word not in CHAT_COMMANDS:
        return f"(unknown command {word}; /help lists them)"
    try:
        if word == "/status":
            lines = [verbs.call("machine")["summary"]]
            for r in _live_runs():
                lines.append(f"  {r['id']}  {r['status']:<8} {r['task']}  step {r['step']}/{r['steps_total']}"
                             + (f"  ASKING: {r['ask']['text']}" if r.get("ask") else ""))
                p = verbs.call("progress", run=r["id"], recent=0)
                if p["last_activity"]:
                    lines.append(f"      last: {p['last_activity']} ({p['seconds_since_activity']} s ago; "
                                 f"{p['tool_calls']} tool calls, {p['model_calls']} model calls)")
                if p["quiet_note"]:
                    lines.append(f"      {p['quiet_note']}")
            return "\n".join(lines)
        rid, rest = _pick_run(rest)
        if word == "/steer":
            if not rest:
                return "(say what the note is: /steer <note>)"
            r = verbs.call("steer", run=rid, text=" ".join(rest))
        elif word == "/reject":
            r = verbs.call("reject", run=rid, why=" ".join(rest))
        else:
            r = verbs.call({"/park": "park_run", "/resume": "resume", "/approve": "approve",
                            "/cancel": "cancel"}[word], run=rid)
    except (verbs.VerbError, ValueError) as e:
        return f"(error) {e}"
    done = {"/park": "parking: it stops at its next tool call and gives the machine back",
            "/resume": "resuming: it waits for the machine, then continues with any notes",
            "/steer": "noted: it reads this at its next boundary", "/approve": "approved",
            "/reject": "rejected: the worker is told no and why", "/cancel": "cancel requested"}[word]
    return f"{r['id']} ({r['task']}, {r['status']}): {done}"


def _busy_note():
    """Said before a message that will wait: the orchestrator needs the machine, a worker has it until its step ends."""
    from . import verbs
    m = verbs.call("machine")
    h = m.get("holder")
    if not h or h["kind"] == "orchestrator":
        return ""
    return (f"(the machine is busy: {m['summary']}. Your message waits for that to finish; "
            "/park stops a run now, Ctrl+C stops waiting.)")


class _EventEcho:
    """While a chat turn works, print what the orchestrator does (its waits, model calls and tool calls) as it
    happens, so nothing changes out of sight."""
    def __init__(self, ref, poll=1.0):
        import threading
        self.ref, self.poll, self.done = ref, poll, threading.Event()
        self.since = time.time()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.done.set()
        self.thread.join(timeout=3)
        self._print_new()

    def _print_new(self):
        from . import verbs
        for e in verbs.ctx.store.events(self.ref, since=self.since):
            self.since = e["ts"]
            if e["kind"] in ("orchestrator", "waiting"):
                print(f"   . {e['detail'][:300]}", flush=True)

    def _loop(self):
        while not self.done.wait(self.poll):
            try:
                self._print_new()
            except Exception:
                pass


def chat_loop(rest):
    """A terminal conversation with the orchestrator (the same `chat` verb the UI uses)."""
    from . import verbs
    conv = rest[rest.index("--conversation") + 1] if "--conversation" in rest else ""
    print("Ariadne orchestrator - it defines and manages tasks; workers do them. Empty line or Ctrl+C to leave.")
    print(f"Commands that act at once, without the model: {', '.join(sorted(CHAT_COMMANDS))} (/help).")
    while True:
        try:
            msg = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not msg:
            return 0
        if msg.startswith("/"):
            print(chat_command(msg) + "\n")
            continue
        busy = _busy_note()
        if busy:
            print(busy)
        conv = conv or f"c{time.strftime('%m%d-%H%M%S')}"
        watch = _EventEcho(conv)
        watch.start()
        try:
            out = verbs.call("chat", message=msg, conversation=conv)
        except verbs.VerbError as e:
            print(f"(error) {e}")
            continue
        except KeyboardInterrupt:
            print("\n(stopped waiting; the orchestrator did not answer that message)\n")
            continue
        finally:
            watch.stop()
        conv = out["conversation"]
        print(f"ariadne> {out['reply']}\n")


def main(argv=None):
    from .bootstrap import start as _start_overlay
    _start_overlay()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    _ensure_project_interpreter(argv)
    if "--watch" in argv:
        argv.remove("--watch")
        from . import activity
        activity.open_window()
    if not argv:
        return overview()
    cmd, rest = argv[0], argv[1:]
    from . import verbs
    cmd = ALIASES.get(cmd, cmd)
    if cmd == "park_run" and (not rest or rest[0].startswith("--")):   # the old global form
        from . import park
        return park.main(rest)
    if cmd == "chat":
        return chat_loop(rest)
    if cmd in verbs.VERBS and cmd not in ("flows",):
        return verb_cli(cmd, rest)
    if cmd == "flows":
        _print(verbs.call("flows"))
        return 0
    if cmd == "local-only":
        from . import local_only
        bad = local_only.check_home()
        print("local-only: OK" if not bad else "local-only: FAIL\n  - " + "\n  - ".join(bad))
        return 1 if bad else 0
    if cmd == "doctor":
        return deps.doctor()
    if cmd == "install":
        return deps.install(system="--system" in rest, models="--models" in rest)
    simple = {"watch": "activity", "resources": "resources", "kv": "kvcache", "browser": "browser",
              "casestudy": "casestudy", "watchdog": "watchdog", "server": "serving", "models": "models"}
    if cmd in simple:
        import importlib
        return importlib.import_module(f"ariadne.{simple[cmd]}").main(rest)
    if cmd == "stop":
        from .daemon import stop_all
        stopped = stop_all(hard="--hard" in rest)
        print(f"Ariadne stopped: the worker and the models. Runs back to you: {', '.join(stopped) or 'none'}")
        return 0
    if cmd == "ui":
        from . import server
        return server.main(rest)
    deps.require()
    if cmd == "serve":
        from . import serve
        return serve.stop() if "--stop" in rest else serve.start()
    if cmd == "up":
        from . import host, serve
        serve.start()
        return host.main(["serve", "--host", "0.0.0.0" if "--lan" in rest else "127.0.0.1"])
    if cmd == "down":
        from . import serve
        return serve.stop()
    if cmd in ("connect", "token"):
        from . import host
        return host.main([cmd, *rest])
    print(f"unknown command '{cmd}'\n{__doc__}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
