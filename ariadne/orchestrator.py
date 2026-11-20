"""Task orchestrator: the store, the worker process and the CLI.

    brief -> route (the flow is explicit) -> plan (Hermes worker, read-only tools)
          -> backbrief (sent back to whoever gave the task) -> sign-off (approve / revise / cancel)
          -> execute (the worker, one Hermes session per task) -> checks (gates at the edge) -> report

One worker process (`python -m ariadne.orchestrator serve`) does all the runs, one at a time, so only one model is
ever on the GPU. Tasks live in .ariadne/tasks.db; MCP servers and the CLI only read and write that table and make
sure the worker is running. Execution itself lives in `worker.py`; this module is the store and the loop around it.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import flows as flowlib
from . import jobs, llm, park, paths
# The worker is a lower layer (it does not import this module at load time). These names stay importable from here
# because every surface and test has always reached for them through `ariadne.orchestrator`.
from .worker import (Worker, RunResult, gates_text, PARKED, TURNS, runtime_run, hermes_run,   # noqa: F401
                     stop_gateway, _turn_end_reason, _clean_output,
                     parse_model_plan, apply_model_overrides, model_summary,
                     needed_models, needed_servers, missing_servers, model_block, chain_for,
                     RESUME_PROMPT, JOBS_RULE, jobs_rule, skills_block, step_scope, _install_system_tools,
                     _reload_models, missing_system, missing_tools)

from .store import (FINAL, WAITING, GATES_QUESTION, GATES_HEAD, SCHEMA, Store, TaskError,   # noqa: F401
                    gate, parse_gates)

# ---------- single worker process ----------

LOCK = paths.STATE / "worker.lock"


def _try_lock(path):
    """Exclusive, non-blocking lock held for the process lifetime. Returns the open file or None."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def _release(f):
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()
    except OSError:
        pass


def worker_running():
    # Resolved at call time: an ARIADNE_STATE (or a test's tmp dir) set after import must still be honoured.
    f = _try_lock(paths.STATE / "worker.lock")
    if f is None:
        return True
    _release(f)
    return False


def ensure_worker():
    from .activity import maybe_open_window
    maybe_open_window()
    return _ensure_worker()


def _ensure_worker():
    """Start the worker process if none is running (detached; its own log; no pipes to the caller)."""
    if os.environ.get("ARIADNE_NO_AUTOSTART") or worker_running():
        return False
    paths.ensure()
    # Outside the caller's session (procs.py): closing the terminal, chat or remote session must not kill it.
    from .procs import spawn_detached
    spawn_detached([paths.PYTHON, "-m", "ariadne.orchestrator", "serve"], paths.LOGS / "worker.log", paths.ROOT,
                   {"PYTHONPATH": str(paths.ROOT), "PYTHONIOENCODING": "utf-8"})
    return True


WORKER_PID = paths.STATE / "worker.pid"


def stop_all(reason="stopped by you", hard=False):
    """Stop Ariadne's background work on purpose: the worker, the Hermes gateways it started, and the model server.
    A task that was running goes back to the person (needs_attention) with its work kept in the workspace.

    hard=True is the kill switch: after the normal walk-down, force-kill anything still holding one of Ariadne's
    ports and clear every stale pid/claim marker, so nothing survives a broken shutdown to poison the next start."""
    from . import park, procs
    from . import serve as model_server
    procs.terminate_job()          # the group, including anything whose parent is already gone
    try:
        pid = json.loads(WORKER_PID.read_text())["pid"]
    except (OSError, ValueError, KeyError):
        pid = 0
    procs.kill_tree(pid)  # the worker and the Hermes run it was waiting on
    WORKER_PID.unlink(missing_ok=True)
    for home in paths.HOMES.glob("*") if paths.HOMES.exists() else []:
        try:
            stop_gateway(home)
        except Exception:
            pass
    model_server.stop()
    if hard:
        procs.kill_on_ports([paths.PORT_MCP, paths.PORT_MODELS, paths.PORT_UI, paths.PORT_BROWSER])
        for stale in paths.STATE.glob("*.pid"):
            try:
                stale.unlink()
            except OSError:
                pass
        for stale in paths.STATE.glob("*.current.json"):
            try:
                stale.unlink()
            except OSError:
                pass
    park.resume()
    st = Store()
    stopped = []
    for t in st.list(50):
        if t["status"] in ("planning", "executing"):
            st.update(t["id"], status="needs_attention", result=f"{reason}; the work so far is in the workspace. "
                                                               "Approve to continue it.")
            st.event(t["id"], "stop", reason)
            stopped.append(t["id"])
        for j in jobs.for_task(t["id"], db_path=st.db_path):   # a job killed with the worker does not run again
            if j["status"] in ("pending", "running"):
                jobs._update(j["id"], st.db_path, status="cancelled")
    return stopped


def ensure_llm(wait=120):
    if llm.is_up():
        return True
    from . import serve as model_server
    print("models are down; starting them", flush=True)
    try:
        model_server.start()
    except SystemExit as e:
        print(f"could not start the models: {e}", flush=True)
    start = time.time()
    while time.time() - start < wait:
        if llm.is_up():
            return True
        time.sleep(2)
    return False


def _code_stamp():
    """Newest change to the worker's code or configuration (Ariadne's modules, flows, skills, model catalog)."""
    files = list((paths.ROOT / "ariadne").glob("*.py")) + list(paths.FLOWS_DIR.rglob("*.yaml")) \
        + list(paths.FLOWS_DIR.rglob("SKILL.md")) + [paths.ROOT / "serving" / "models.yaml"]
    return max((f.stat().st_mtime for f in files if f.exists()), default=0)


def _reconcile(store):
    """A worker that starts finds whatever a previous worker left mid-run (crash, kill, reboot) and hands it back.

    Nothing else can do this: the worker holds the single-process lock, so any row still in planning/executing at
    this point has no worker behind it. Silence here is what leaves a task reading `executing` for two days.
    """
    for t in store.list(50):
        if t["status"] in ("planning", "executing"):
            store.update(t["id"], status="needs_attention",
                         result="The worker restarted while this task was running. The work so far is in the "
                                "workspace. Approve to continue it, or revise it.")
            store.event(t["id"], "recover", "no worker behind it (crash, kill or reboot); back to the person")


def _watchdog(store):
    """Start the babysitter for as long as this worker lives; returns its stop function.

    A script, never a model: it samples RAM/VRAM/health on an interval and escalates warn -> unload -> kill ->
    `needs_attention` with the readings, logging every sample (docs/COVERAGE.md, the runtime contract).
    """
    from . import watchdog
    stop = watchdog.start(store)
    print(f"watchdog: every {watchdog.INTERVAL:g} s, log {watchdog.LOG}", flush=True)
    return stop


def serve(idle_exit=1800):
    from . import bootstrap
    bootstrap.start()          # root and vendor/hermes ahead of site-packages, before any Hermes import
    from .deps import require
    from . import local_only
    require()
    bad = local_only.check_home()
    if bad:
        # Re-checked at launch, not only when the profile was written: inference stays on this machine or the LAN.
        print("refusing to start: inference must stay local:\n  - " + "\n  - ".join(bad), flush=True)
        return 2
    lock = _try_lock(LOCK)
    if lock is None:
        print("another Ariadne worker is running", flush=True)
        return 2
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} worker up (pid {os.getpid()})", flush=True)
    WORKER_PID.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}))
    try:
        from .resources import detect_at_boot
        detect_at_boot(log=lambda s: print(s, flush=True))  # GPU/RAM limits for this machine, logged at every start
    except Exception as e:
        print(f"limits: could not measure this machine ({e})", flush=True)
    for name, home in flowlib.compile_all().items():
        print(f"  flow {name} -> {home}", flush=True)
        stop_gateway(home)  # a gateway left from an earlier worker still has the old config; the next run restarts it
    w, last, stamp, restart = Worker(), time.time(), _code_stamp(), False
    _reconcile(w.store)
    stop_dog = _watchdog(w.store)
    try:
        while True:
            if _code_stamp() > stamp:  # updated code or config: hand over to a fresh worker between tasks
                restart = True
                return 0
            try:  # between tasks: apply a new resource profile (restarts the model servers)
                from . import serve as model_server
                model_server.apply_if_changed()
            except (Exception, SystemExit) as e:
                print(f"could not apply the resource profile: {e}", flush=True)
            try:  # due schedules become normal tasks in their own session (a standing brief, not a new kind of job)
                from . import schedule
                for name, tid in schedule.sweep(w.store):
                    print(f"schedule {name} -> {tid}", flush=True)
            except Exception as e:
                print(f"schedule sweep failed: {e}", flush=True)
            if any(t["status"] in ("new", "approved") for t in w.store.list(50)):
                if not ensure_llm():
                    print("local models are not reachable; waiting", flush=True)
                    time.sleep(10)
                    continue
            if w.run_once():
                last = time.time()
                continue
            if idle_exit and time.time() - last > idle_exit:
                print("idle; exiting", flush=True)
                return 0
            time.sleep(2)
    finally:
        stop_dog()
        _release(lock)
        if restart:
            print("code or config changed; starting a fresh worker", flush=True)
            ensure_worker()


# ---------- CLI ----------

def _default_workspace():
    """The folder the person is standing in: the git root if there is one, else the cwd.

    A task given from inside a repo must apply to that repo. Defaulting to empty silently sent the work to
    .ariadne/workspace instead, where the model changed a copy nobody was looking at.
    """
    cwd = os.getcwd()
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True,
                           timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd


def _default_session(workspace: str = "") -> str:
    """A workstream is a folder: tasks given in the same repo build on each other.

    The design's default was "session = repo folder name", so a second task in the same checkout continues the
    first instead of starting a stranger every time.
    """
    name = Path(workspace or _default_workspace()).name
    return re.sub(r"[^\w.-]+", "-", name).strip("-") or "main"


def _print(t):
    print(json.dumps(t, indent=2, default=str))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ariadne", description="Ariadne tasks: brief, backbrief, sign-off, execute")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit"); s.add_argument("text", nargs="?", default="")
    s.add_argument("--file", default="", help="read the task text from a file (long briefs, no shell quoting)")
    s.add_argument("--workspace", default="", help="the folder the task applies to (default: the git root of the "
                                                   "folder you run this from, else the current folder)")
    s.add_argument("--flow", default="", help="an approved flow (required: the person chooses, nothing routes)")
    s.add_argument("--model", default="", help="the agent model for this task (required; see: ariadne models)")
    s.add_argument("--wait", type=int, default=0)
    s.add_argument("--session", default="", help="continue this Hermes session (default: a new one for the task)")
    s.add_argument("--gate", action="append", default=[], help="a check gate ('run: pytest -q' for a command); repeatable")
    s.add_argument("--json", action="store_true", help="machine output: the task row as JSON, no following")
    s.add_argument("--no-follow", action="store_true", help="return as soon as the task is queued")
    gt = sub.add_parser("gates"); gt.add_argument("id"); gt.add_argument("gates", nargs="+")
    g = sub.add_parser("get"); g.add_argument("id")
    w = sub.add_parser("wait"); w.add_argument("id"); w.add_argument("--timeout", type=int, default=600)
    a = sub.add_parser("approve"); a.add_argument("id")
    a.add_argument("--model", action="append", default=[], metavar="STEP=NAME",
                   help="change a step's model before locking the plan (STEP may be 'all'); repeatable")
    r = sub.add_parser("revise"); r.add_argument("id"); r.add_argument("feedback")
    c = sub.add_parser("cancel"); c.add_argument("id")
    f = sub.add_parser("feedback"); f.add_argument("id"); f.add_argument("text")
    sub.add_parser("list")
    sub.add_parser("sessions")
    sub.add_parser("serve")
    sub.add_parser("flows")
    args = ap.parse_args(argv)
    if args.cmd == "serve":
        return serve()
    if args.cmd == "flows":
        for name, home in flowlib.compile_all().items():
            print(f"{name}: {home}")
        return 0
    from . import service
    st = service.store()
    if args.cmd == "submit":
        text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
        workspace = args.workspace or _default_workspace()
        try:
            tid = service.submit(text, source="cli", workspace=workspace, flow=args.flow, model=args.model,
                                 session=args.session or _default_session(workspace), gates=args.gate, store=st)
        except TaskError as e:
            print(str(e))
            return 2
        ensure_worker()
        if args.json:
            _print(service.wait(tid, args.wait, store=st) if args.wait else {"id": tid, "status": "new"})
        elif args.no_follow:
            print(f"{tid}: queued. Follow it with: ariadne follow {tid}")
        else:
            # The point of giving a task is to see it plan and then read the backbrief. `--json` is the escape
            # hatch for scripts; the default is the human loop the README describes.
            from . import console
            return console.follow(st, tid, timeout=args.wait or 3600)
    elif args.cmd == "get":
        _print(service.task(args.id, store=st))
    elif args.cmd == "wait":
        ensure_worker()
        _print(service.wait(args.id, args.timeout, store=st))
    elif args.cmd == "approve":
        service.approve(args.id, ",".join(args.model) or None, store=st); ensure_worker()
        _print(service.task(args.id, events=False, store=st))
    elif args.cmd == "revise":
        service.revise(args.id, args.feedback, store=st); ensure_worker()
        _print(service.task(args.id, events=False, store=st))
    elif args.cmd == "gates":
        service.set_gates(args.id, args.gates, store=st); ensure_worker()
        _print(service.task(args.id, events=False, store=st))
    elif args.cmd == "feedback":
        service.feedback(args.id, args.text, store=st)
        print("feedback recorded; a larger model folds it into the flow's skills (save_skill)")
    elif args.cmd == "cancel":
        service.cancel(args.id, store=st); _print(service.task(args.id, events=False, store=st))
    elif args.cmd == "sessions":
        for s in service.sessions(store=st):
            print(f"{s['name']:<28} {s['tasks']:>3} tasks  segment {s['segment']:<3} {s['flow'] or '-':<8} "
                  f"{(s['summary'] or '').splitlines()[0][:60] if s['summary'] else ''}")
    elif args.cmd == "list":
        for t in service.tasks(store=st):
            print(f"{t['id']}  {t['status']:<17} {t['flow'] or '-':<8} {t['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
