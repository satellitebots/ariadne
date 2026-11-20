"""Schedules: a standing brief, not a new kind of job (docs/DESIGN-RESET.md).

A schedule is a row in the store: a name (which is also the session its runs continue), a cron expression, the brief,
and the flow/model/workspace/gates it inherited from the session when it was created. Each due occurrence is a normal
`service.submit(source="schedule", session=<name>)`, so it goes through the same drill, the same gates and the same
report as any other task - and accumulates in one chain.

The scheduler is the worker's serve loop (`sweep()` before each claim). No separate daemon, no model in the control
path: due-ness is arithmetic on the clock. A run that fails goes `needs_attention`; the next occurrence still comes,
but nothing retries in a loop.
"""
import json
import time
from datetime import datetime, time as dtime, timedelta

from .errors import TaskError

ALIASES = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0",
           "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *"}
RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
FIELD = ("minute", "hour", "day of month", "month", "day of week")


class ScheduleError(ValueError):
    pass


def parse(expr):
    """Five cron fields as sorted tuples of ints. Raises ScheduleError with the field that is wrong."""
    text = ALIASES.get((expr or "").strip().lower(), (expr or "").strip())
    parts = text.split()
    if len(parts) != 5:
        raise ScheduleError(f"a cron expression has five fields (minute hour day-of-month month day-of-week); got "
                            f"{len(parts)} in {expr!r}")
    out = []
    for part, (lo, hi), name in zip(parts, RANGES, FIELD):
        values = set()
        for chunk in part.split(","):
            step = 1
            if "/" in chunk:
                chunk, _, step_text = chunk.partition("/")
                try:
                    step = int(step_text)
                except ValueError:
                    raise ScheduleError(f"{name}: '{step_text}' is not a step")
                if step < 1:
                    raise ScheduleError(f"{name}: a step must be 1 or more")
            if chunk == "*":
                start, end = lo, hi
            elif "-" in chunk:
                a, _, b = chunk.partition("-")
                try:
                    start, end = int(a), int(b)
                except ValueError:
                    raise ScheduleError(f"{name}: '{chunk}' is not a range")
            else:
                try:
                    start = end = int(chunk)
                except ValueError:
                    raise ScheduleError(f"{name}: '{chunk}' is not a number")
            if not (lo <= start <= hi and lo <= end <= hi and start <= end):
                raise ScheduleError(f"{name}: {chunk} is outside {lo}-{hi}")
            values |= set(range(start, end + 1, step))
        if name == "day of week":
            values = {0 if v == 7 else v for v in values}
        out.append(tuple(sorted(values)))
    return tuple(out)


def next_after(expr, ts):
    """The first minute strictly after `ts` that matches, or None within four years (Feb 29 is the edge)."""
    minutes, hours, doms, months, dows = parse(expr) if isinstance(expr, str) else expr
    t = datetime.fromtimestamp(ts if ts else time.time()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    dom_restricted = set(doms) != set(range(1, 32))
    dow_restricted = set(dows) != set(range(0, 7))
    day = t.date()
    for _ in range(366 * 4):
        dow = (day.weekday() + 1) % 7
        day_ok = ((day.day in doms) or (dow in dows)) if (dom_restricted and dow_restricted) \
            else ((day.day in doms) and (dow in dows))
        if day.month in months and day_ok:
            for h in hours:
                for m in minutes:
                    candidate = datetime.combine(day, dtime(h, m))
                    if candidate >= t:
                        return candidate.timestamp()
        day += timedelta(days=1)
    return None


def due(schedule, now=None):
    """Is this schedule owed a run now? The first run is the first cron boundary after it was created."""
    now = time.time() if now is None else now
    base = schedule.get("last_run") or schedule.get("created") or 0
    if not base:
        return False
    nxt = next_after(schedule["cron"], base)
    return nxt is not None and nxt <= now


def sweep(store, now=None, submit=None):
    """Submit one task per due schedule. Returns [(name, task id)]. `submit` is injectable for tests."""
    from . import service
    now = time.time() if now is None else now
    done = []
    for s in store.schedules(enabled_only=True):
        if not due(s, now):
            continue
        try:
            task_id = (submit or _submit)(s, store)
        except TaskError as e:
            # A schedule the rulebook refuses (a model uninstalled, a flow renamed) is stopped, not retried forever.
            store.schedule_update(s["name"], enabled=0)
            store.event(s.get("last_task") or s["name"], "schedule",
                        f"disabled: {s['name']} could not be submitted: {e}")
            continue
        store.schedule_ran(s["name"], now, task_id)
        store.event(task_id, "schedule", f"from schedule {s['name']} ({s['cron']})")
        done.append((s["name"], task_id))
    return done


def _submit(schedule, store):
    from . import service
    return service.submit(schedule["brief"], source="schedule", workspace=schedule.get("workspace") or "",
                          flow=schedule["flow"], model=schedule["model"], session=schedule["name"],
                          gates=json.loads(schedule.get("gates") or "[]"), store=store)


def _flag(args, name, default=""):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def main(argv=None):
    """`ariadne schedules [create SESSION --cron EXPR [--brief TEXT] | on NAME | off NAME | rm NAME]`."""
    import sys
    from . import service
    argv = list(sys.argv[1:] if argv is None else argv)
    store = service.store()
    cmd = argv[0] if argv else "list"
    rest = argv[1:]
    try:
        if cmd in ("create", "add"):
            if not rest:
                print("create needs a session name: ariadne schedules create <session> --cron \"0 2 * * *\"")
                return 2
            row = service.schedule_create(rest[0], _flag(rest, "--cron"), _flag(rest, "--brief"), store=store)
            print(f"schedule {row['name']}: {row['cron']}  {row['flow']}/{row['model']}  {row['workspace'] or '-'}")
            return 0
        if cmd in ("on", "off"):
            row = service.schedule_set(rest[0], cmd == "on", store=store)
            print(f"{row['name']}: {'on' if row['enabled'] else 'off'}")
            return 0
        if cmd in ("rm", "delete"):
            service.schedule_delete(rest[0], store=store)
            print(f"deleted {rest[0]}")
            return 0
    except TaskError as e:
        print(str(e))
        return 2
    rows = store.schedules()
    if not rows:
        print("no schedules yet. Create one from a session:  ariadne schedules create <session> --cron \"0 2 * * *\"")
        return 0
    now = time.time()
    for s in rows:
        nxt = next_after(s["cron"], s["last_run"] or s["created"]) if s["cron"] else None
        when = datetime.fromtimestamp(nxt).strftime("%Y-%m-%d %H:%M") if nxt else "-"
        print(f"{'on ' if s['enabled'] else 'off'}  {s['name']:<24} {s['cron']:<16} next {when:<16} "
              f"{s['flow']}/{s['model']}  last {s['last_task'] or '-'}")
    return 0
