"""Parking: a deliberate pause of the running task so the person can have the local model.

Nothing is ever parked automatically. Parking is requested (desktop button, `python -m ariadne park`); the worker
lets the model call or tool call in flight finish, stops the Hermes run at that step boundary, parks its KV cache,
and waits. Resuming (button, `python -m ariadne park --resume`) wakes the cache and continues the same Hermes session.

The flag is a file so every process (worker, desktop plugin backend, CLI) sees the same state."""
import json
import sys
import time

from . import paths

FLAG = paths.STATE / "park.json"


def requested() -> dict | None:
    try:
        return json.loads(FLAG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def request(by="desktop") -> dict:
    cur = requested()
    if cur:
        return cur
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    state = {"requested": time.time(), "by": by, "parked": False}
    FLAG.write_text(json.dumps(state), encoding="utf-8")
    return state


def mark_parked(task_id, model):
    cur = requested() or {"requested": time.time(), "by": "?"}
    cur.update(parked=True, parked_at=time.time(), task=task_id, model=model)
    FLAG.write_text(json.dumps(cur), encoding="utf-8")


def resume():
    """Clear the park flag.

    A reader (the worker, `park --status`, the activity window) may hold the file for a moment, and Windows refuses
    to unlink an open file (WinError 32). Resuming must not fail because someone looked, so a busy file is retried
    briefly instead of raised.
    """
    for _ in range(20):
        try:
            FLAG.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.05)


def wait_resumed(poll=3.0):
    while requested():
        time.sleep(poll)


class StepBoundary:
    """Watches a Hermes home's agent.log: true once a model call or a tool call has finished after `start()`."""
    MARKS = ("agent.conversation_loop: API call #", "agent.tool_executor: tool ")

    def __init__(self, home):
        self.log = home / "logs" / "agent.log"
        self.pos = None

    def start(self):
        self.pos = self.log.stat().st_size if self.log.exists() else 0

    def reached(self) -> bool:
        if self.pos is None:
            self.start()
            return False
        try:
            with open(self.log, "rb") as f:
                f.seek(self.pos)
                new = f.read().decode("utf-8", "replace")
        except OSError:
            return False
        return any(m in new for m in self.MARKS)


def status(store=None) -> dict:
    """What the desktop shows: the task holding the model (if any), park state, what needs the person, recent activity."""
    from . import activity
    from .orchestrator import Store
    store = store or Store()
    rows = store.list(limit=30)
    active = [t for t in rows if t["status"] in ("planning", "executing")]
    t = active[0] if active else None
    flag = requested()
    needs = [{"id": r["id"], "status": r["status"], "text": (r["text"] or "").splitlines()[0][:120]}
             for r in rows if r["status"] in ("awaiting_gates", "awaiting_signoff", "needs_attention")]
    out = {"busy": bool(t), "park": flag, "recent": activity.recent(10), "task": None, "needs": needs}
    if t:
        full = store.get(t["id"])
        ev = [e for e in full.get("events", []) if " feedback:" not in e[:20]]
        out["task"] = {"id": t["id"], "status": t["status"], "flow": t.get("flow"),
                       "text": (t["text"] or "").strip().splitlines()[0][:140],
                       "since": t.get("updated"), "last": ev[-1] if ev else None}
    return out


def main(argv):
    if "--resume" in argv:
        resume()
        print("resumed: the worker continues where it stopped")
    elif "--status" in argv:
        print(json.dumps(status(), indent=2, default=str))
    else:
        request("cli")
        print("park requested: the running task stops at its next step boundary and waits for --resume")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
