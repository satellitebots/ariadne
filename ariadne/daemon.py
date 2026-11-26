"""The background process: one per machine, it runs the engine (schedules and queued runs) for as long as it lives.

    python -m ariadne.daemon serve

It runs detached from whatever started it (procs.spawn_detached), so closing a terminal, a chat or a remote session
never kills a run halfway; it stops only through `ariadne stop` or the watch window. One process holds the lock, so
there is one engine and one owner of the broker's worker lease per machine.
"""
import json
import os
import sys
import time

from . import paths

LOCK = paths.STATE / "worker.lock"
WORKER_PID = paths.STATE / "worker.pid"


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
    f = _try_lock(paths.STATE / "worker.lock")   # resolved at call time (tests move STATE)
    if f is None:
        return True
    _release(f)
    return False


def ensure_worker():
    """Start the background process if none is running (detached; its own log)."""
    if os.environ.get("ARIADNE_NO_AUTOSTART") or worker_running():
        return False
    from .activity import maybe_open_window
    maybe_open_window()
    paths.ensure()
    from .procs import spawn_detached
    spawn_detached([paths.PYTHON, "-m", "ariadne.daemon", "serve"], paths.LOGS / "worker.log", paths.ROOT,
                   {"PYTHONPATH": str(paths.ROOT), "PYTHONIOENCODING": "utf-8"})
    return True


def stop_all(reason="stopped by you", hard=False):
    """Stop Ariadne on purpose: the background process, its workers, and the model server. Live runs go back to the
    person (`needs_you`) with their work kept. hard=True also force-kills anything on Ariadne's ports and clears
    stale pid files, so nothing survives a broken shutdown."""
    from . import durable, jobs, park, procs
    from . import serve as model_server
    procs.terminate_job()
    try:
        pid = json.loads(WORKER_PID.read_text())["pid"]
    except (OSError, ValueError, KeyError):
        pid = 0
    procs.kill_tree(pid)
    WORKER_PID.unlink(missing_ok=True)
    model_server.stop()
    if hard:
        procs.kill_on_ports([paths.PORT_MCP, paths.PORT_MODELS, paths.PORT_UI, paths.PORT_BROWSER])
        for stale in list(paths.STATE.glob("*.pid")) + list(paths.STATE.glob("*.current.json")):
            try:
                stale.unlink()
            except OSError:
                pass
    park.resume()
    store = durable.Store()
    stopped = []
    for r in store.runs(live=True, limit=200):
        store.run_set(r["id"], status="needs_you" if r["status"] != "queued" else "cancelled", ended=time.time(),
                      error=f"{reason}; the work so far is in the workspace")
        store.event(r["id"], "stop", reason)
        stopped.append(r["id"])
        for j in jobs.for_task(r["id"]):
            if j["status"] in ("pending", "running"):
                jobs._update(j["id"], None, status="cancelled")
    return stopped


def _code_stamp():
    """Newest change to Ariadne's code or configuration (modules, flows, skills, the model catalog)."""
    files = list((paths.ROOT / "ariadne").glob("*.py")) + list(paths.FLOWS_DIR.rglob("*.yaml")) \
        + list(paths.FLOWS_DIR.rglob("SKILL.md")) + [paths.ROOT / "serving" / "models.yaml"]
    return max((f.stat().st_mtime for f in files if f.exists()), default=0)


def reconcile(store):
    """Runs a dead process left live go back to the person; queued runs stay queued; a run you had asked to cancel
    is cancelled (the worker died before it could do it)."""
    for r in store.runs(live=True, limit=200):
        if (r.get("error") or "").startswith("cancel requested"):
            store.run_set(r["id"], status="cancelled", ended=time.time())
            store.event(r["id"], "recover", "cancelled: you asked, and its worker had stopped")
        elif r["status"] != "queued":
            store.run_set(r["id"], status="needs_you", ended=time.time(),
                          error="the worker restarted during this run; the work so far is in the workspace. "
                                "Rerun it to start again.")
            store.event(r["id"], "recover", "no worker behind it (crash, kill or reboot)")


def _watchdog(store, broker):
    """The watchdog, told what runs by the broker: it never unloads a model under a lease holder, and a run it has
    to stop is cancelled at its boundary with the readings."""
    from . import watchdog

    def holder():
        h = broker.holder()
        return h["ref"] if h else ""

    def flag(ref, why):
        if ref and store.run(ref):
            store.run_set(ref, error="cancel requested")
            store.event(ref, "watchdog", why)
            return f"flagged {ref}"
        return "no run was holding the machine"

    stop = watchdog.start(store, running=holder, flag=flag)
    print(f"watchdog: every {watchdog.INTERVAL:g} s, log {watchdog.LOG}", flush=True)
    return stop


def serve(idle_exit=1800):
    from . import bootstrap
    bootstrap.start()          # root and vendor/hermes ahead of site-packages, before any Hermes import
    from .deps import require
    from . import engine, flows as flowlib, local_only
    require()
    bad = local_only.check_home()
    if bad:
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
        detect_at_boot(log=lambda s: print(s, flush=True))
    except Exception as e:
        print(f"limits: could not measure this machine ({e})", flush=True)
    for name, home in flowlib.compile_all().items():
        print(f"  flow {name} -> {home}", flush=True)
        engine.stop_gateway(home)
    eng, last, stamp, restart = engine.Engine(), time.time(), _code_stamp(), False
    reconcile(eng.store)
    stop_dog = _watchdog(eng.store, eng.broker)
    try:
        while True:
            if _code_stamp() > stamp:   # updated code or config: hand over to a fresh process between runs
                restart = True
                return 0
            try:                        # between runs: apply a new resource profile
                from . import serve as model_server
                model_server.apply_if_changed()
            except (Exception, SystemExit) as e:
                print(f"could not apply the resource profile: {e}", flush=True)
            if eng.run_once():          # sweeps due schedules, then the oldest queued run
                last = time.time()
                continue
            scheduled = any(t["scheduled"] and t["next_due"] for t in eng.store.tasks())
            if idle_exit and time.time() - last > idle_exit and not scheduled:   # a schedule keeps it up
                print("idle; exiting", flush=True)
                return 0
            time.sleep(2)
    finally:
        stop_dog()
        _release(lock)
        if restart:
            print("code or config changed; starting a fresh worker", flush=True)
            ensure_worker()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["serve"]:
        return serve()
    print("usage: python -m ariadne.daemon serve")
    return 2


if __name__ == "__main__":
    sys.exit(main())
