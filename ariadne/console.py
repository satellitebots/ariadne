"""The model-free control surface: what needs me, follow a task, sign off, answer gates.

The drill does not need a second local model. Everything a person must decide - read the backbrief, approve,
revise, cancel, supply gates - is a read or a write against the same SQLite store the worker uses. Routing those
decisions through a chat model costs a GPU swap per turn and invites a relay to paraphrase or "helpfully" approve.

These commands never touch a model: they work while the GPU is busy, while the models are down, and from another
window. The chat surfaces stay available for conversation; they are no longer the only door.
"""
import json
import re
import sys
import textwrap
import time

from . import service
from .errors import TaskError
from .orchestrator import FINAL, WAITING, ensure_worker, worker_running

LABEL = {"new": "queued", "awaiting_gates": "needs gates", "planning": "planning",
         "awaiting_signoff": "backbrief ready", "approved": "approved, queued", "executing": "executing",
         "needs_attention": "needs you", "done": "done", "failed": "failed", "cancelled": "cancelled",
         "rejected": "rejected", "timed_out": "out of time"}


def label(t) -> str:
    return LABEL.get(t.get("status"), t.get("status") or "?")


def age(ts) -> str:
    if not ts:
        return ""
    s = max(0, int(time.time() - float(ts)))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def gates_of(t) -> list:
    try:
        return json.loads(t.get("gates") or "[]")
    except ValueError:
        return []


def next_step(t) -> str:
    """The one command that moves this task forward."""
    tid, st = t["id"], t.get("status")
    if st == "awaiting_gates":
        return f'ariadne gates {tid} "run: pytest -q" "README documents every command"'
    if st in ("awaiting_signoff", "needs_attention"):
        return f'ariadne ok {tid}   |   ariadne fix {tid} "what to change"   |   ariadne no {tid}'
    if st in ("planning", "executing", "new", "approved"):
        return f"ariadne follow {tid}"
    return f"ariadne show {tid}"


def _block(title: str, text: str, indent: int = 2, width: int = 96) -> list:
    lines = [f"{title}"]
    for line in (text or "").strip().splitlines():
        if not line.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(line.rstrip(), width=width,
                                   initial_indent=" " * indent, subsequent_indent=" " * indent) or [""])
    return lines


def _orphaned(t) -> bool:
    """A row left in planning/executing with no worker behind it (crash, kill, reboot)."""
    return t.get("status") in ("planning", "executing") and not worker_running()


def adopt(store, tid: str):
    """Hand an orphaned task back to the person before acting on it, so ok/fix work on a crashed run."""
    return service.adopt(tid, store=store)


def render_task(t: dict, events: bool = True) -> str:
    """A task as a person reads it: state, request, gates, backbrief or report, next action."""
    out = [f"{t['id']}  ·  {label(t)}  ·  {t.get('flow') or 'routing'}"
           + (f"  ·  session {t['session']}" if t.get("session") and t["session"] != t["id"] else "")
           + (f"  ·  {age(t.get('updated'))} ago" if t.get("updated") else "")]
    if _orphaned(t):
        out.append("(no worker is running behind this task: the work so far is kept in the workspace)")
    out += _block("Request", t.get("text") or "")
    g = gates_of(t)
    if g:
        out.append("Check gates")
        out += [f"  G{i}  [{x['type']}]  {x['text']}" for i, x in enumerate(g, 1)]
    elif t.get("status") == "awaiting_gates":
        out.append("Check gates: none yet - nothing starts until they are set")
    if t.get("plan") and t.get("status") in ("awaiting_signoff", "approved", "executing", "needs_attention",
                                             "done", "failed"):
        out += _block("Backbrief", t["plan"])
    if t.get("result"):
        out += _block("Report" if t.get("status") == "done" else "Result", t["result"])
    if t.get("error"):
        out += _block("Error", t["error"])
    if events and t.get("events"):
        out.append("Activity")
        out += [f"  {e.splitlines()[0][:160]}" for e in t["events"][-8:]]
    out.append(f"Next: {next_step(t)}")
    return "\n".join(out)


def inbox(store=None) -> str:
    """What needs the person, what is running (or only looks like it), and what finished recently."""
    store = store or service.store()
    alive = worker_running()
    rows = [service.task(r["id"], events=False, store=store) for r in service.tasks(40, store=store)]
    waiting = [t for t in rows if t["status"] in WAITING]
    moving = [t for t in rows if t["status"] in ("new", "approved", "planning", "executing")]
    stale = [t for t in moving if t["status"] in ("planning", "executing") and not alive]
    running = [t for t in moving if t not in stale]
    recent = [t for t in rows if t["status"] in FINAL][:5]
    out = []
    if waiting:
        out.append(f"NEEDS YOU ({len(waiting)})")
        for t in waiting:
            out.append(f"  {t['id']}  {label(t):<15} {t.get('flow') or '-':<8} {age(t.get('updated')):>4}  "
                       f"{(t.get('text') or '').splitlines()[0][:70]}")
    else:
        out.append("NEEDS YOU (0)")
    if stale:
        out.append(f"\nSTOPPED, NO WORKER ({len(stale)})")
        for t in stale:
            out.append(f"  {t['id']}  {label(t):<15} {age(t.get('updated')):>4}  "
                       f"{(t.get('text') or '').splitlines()[0][:70]}")
        out.append("  the work so far is in the workspace; ariadne ok <id> continues it")
    if running:
        out.append(f"\nQUEUED / RUNNING ({len(running)})")
        for t in running:
            out.append(f"  {t['id']}  {label(t):<15} {t.get('flow') or '-':<8} {age(t.get('updated')):>4}  "
                       f"{(t.get('text') or '').splitlines()[0][:70]}")
    if recent:
        out.append("\nRECENT")
        for t in recent:
            out.append(f"  {t['id']}  {label(t):<15} {age(t.get('updated')):>4}  "
                       f"{(t.get('text') or '').splitlines()[0][:70]}")
    first = (waiting or stale or [None])[0]
    if first:
        out.append(f"\nNext: ariadne show {first['id']}   then   ariadne ok {first['id']}")
    elif not running:
        out.append('\nNothing is waiting. Give a task:  ariadne submit "what to do" --gate "run: pytest -q"')
    return "\n".join(out)


def resolve(store, tid: str = "") -> str:
    """The task the person means: an exact id, a unique prefix, else the only one that needs them."""
    tid = (tid or "").strip()
    if tid:
        try:
            service.task(tid, events=False, store=store)
            return tid
        except TaskError:
            pass
        matches = [r["id"] for r in service.tasks(50, store=store) if r["id"].startswith(tid)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise TaskError(f"no task {tid}")
        raise TaskError("that id matches several: " + ", ".join(matches))
    waiting = [r for r in service.tasks(50, store=store) if r["status"] in WAITING]
    if len(waiting) == 1:
        return waiting[0]["id"]
    if len(waiting) > 1:
        raise TaskError("several tasks need you; name one:\n  "
                        + "\n  ".join(f"{r['id']}  {label(r)}  {(r['text'] or '')[:60]}" for r in waiting))
    recent = service.tasks(1, store=store)
    if not recent:
        raise TaskError("no tasks yet")
    return recent[0]["id"]


def _section(text: str, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.*)$", text or "", re.M | re.I)
    return m.group(1).strip() if m else ""


def clean_step(text: str) -> str:
    """A step without its '- tools: ... - model: ...' tail: those become columns of their own."""
    parts = [p.strip() for p in (text or "").split(" - ")]
    keep = [p for p in parts if not re.match(r"^(tools?|model)\s*:", p, re.I)]
    return " - ".join(keep).strip() or (text or "").strip()


def header(t) -> str:
    model = ""
    try:
        model = (json.loads(t.get("models") or "{}") or {}).get("agent") or ""
    except ValueError:
        pass
    return (f"{t.get('flow') or 'routing'} · session {t.get('session') or t['id']} · {t['id']}"
            f"   {model}  ● {label(t)}  {age(t.get('created'))}")


MARK = {"route": "✓", "backbrief": "✓", "sign-off": "✓", "plan": "●", "execute": "●", "checkpoint": "◇",
        "compress": "◇", "qa": "✓", "checks": "✓", "job": "▪", "kv": "·", "park": "⏸", "recover": "⚠",
        "vram": "⏻"}


def paint(line: str) -> str:
    kind = line.split(" ", 1)[-1].split(":", 1)[0] if ":" in line else ""
    for k, mark in MARK.items():
        if kind.startswith(k):
            return f"  {mark} {line}"
    return f"  · {line}"


def brief_view(t) -> str:
    """The backbrief as the document it is: mission, steps with their models, gates, risks, questions."""
    body = t.get("plan") or ""
    cut = body.find("MODEL PLAN (sign-off locks these")
    plan = body[:cut] if cut > 0 else body
    out = ["", "──── BACKBRIEF " + "─" * 48]
    mission = _section(plan, "MISSION")
    if mission:
        out.append(f"MISSION  {mission}")
    try:
        steps = (json.loads(t.get("models") or "{}") or {}).get("steps") or []
    except ValueError:
        steps = []
    out.append("STEPS")
    if steps:
        width = max(len(str(s["n"])) for s in steps)
        for s in steps:
            out.append(f"  {str(s['n']).ljust(width)}  {clean_step(s['text'])[:56]:<56}  {s['model']}")
    else:
        numbered = [l.strip() for l in plan.splitlines() if re.match(r"^\s*\d+[.)]", l)]
        out += [f"  {l}" for l in numbered] or ["  (the plan did not number its steps)"]
    gates = gates_of(t)
    if gates:
        out.append("CHECKS")
        out += [f"  G{i} [{g['type']}] {g['text']}" for i, g in enumerate(gates, 1)]
    risks = _section(plan, "RISKS")
    if risks:
        out.append(f"RISKS    {risks}")
    questions = _section(plan, "QUESTIONS")
    if questions and questions.lower() != "none":
        out.append(f"QUESTIONS {questions}")
    out.append("─" * 60)
    return "\n".join(out)


def _ask(prompt: str) -> str:
    try:
        return (input(prompt) or "").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "d"


def _change_model(store, t, ask, out) -> bool:
    """Pick a different model for one step (or all) from a numbered list, then lock the plan."""
    try:
        steps = (json.loads(t.get("models") or "{}") or {}).get("steps") or []
    except ValueError:
        steps = []
    if not steps:
        print("  this task has no model plan to change", file=out)
        return False
    for s in steps:
        print(f"  {s['n']}  {s['model']:<20} {clean_step(s['text'])[:50]}", file=out)
    which = (ask("step number, or 'all' > ") or "").strip().lower()
    if not which:
        return False
    try:
        from .models import load as load_catalog
        cat = load_catalog()
    except Exception:
        cat = None
    # Offer the models that can actually do this step: an agent step takes agent models, a drafting step a
    # generate model, an image step an image model.
    kind = "agent"
    if cat is not None:
        current = next((s["model"] for s in steps if which == "all" or str(s["n"]) == which), "")
        try:
            kind = cat.get(current).kind if current else "agent"
        except Exception:
            kind = "agent"
    choices = [m.name for m in cat.pickable() if m.kind == kind] if cat is not None else []
    if choices:
        print("  models: " + "   ".join(f"[{i}] {n}" for i, n in enumerate(choices, 1)), file=out)
    answer = (ask("model (number or name) > ") or "").strip()
    if not answer:
        return False
    name = choices[int(answer) - 1] if answer.isdigit() and choices and 1 <= int(answer) <= len(choices) else answer
    try:
        service.approve(t["id"], {which: name}, store=store)
    except TaskError as e:
        print(f"  {e}", file=out)
        return False
    ensure_worker()
    print(f"  locked: step {which} -> {name}", file=out)
    return True


def signoff(store, t, ask=None, out=None) -> str:
    """The decision, taken on the backbrief itself. Returns approved / revised / cancelled / detached."""
    out = out or sys.stdout
    ask = ask or _ask
    tid = t["id"]
    while True:
        choice = (ask("[a]pprove  [m]odels  [r]evise  [c]ancel  [d]etach > ") or "").strip().lower()
        choice = choice[:1] if choice else ""
        if choice == "a":
            service.approve(tid, store=store)
            ensure_worker()
            print("  approved; executing", file=out)
            return "approved"
        if choice == "m":
            if _change_model(store, t, ask, out):
                print("  approved with the changed model; executing", file=out)
                return "approved"
            continue
        if choice == "r":
            feedback = (ask("what should change? > ") or "").strip()
            if not feedback:
                continue
            service.revise(tid, feedback, store=store)
            ensure_worker()
            print("  sent back to planning; a new backbrief follows", file=out)
            return "revised"
        if choice == "c":
            service.cancel(tid, store=store)
            print("  cancelled", file=out)
            return "cancelled"
        if choice in ("d", "", "q"):
            print("  detached; the task keeps running. `ariadne` shows what needs you.", file=out)
            return "detached"


def follow(store, tid: str, timeout: float = 1800, poll: float = 1.0, stream=None, ask=None,
           interactive: bool | None = None) -> int:
    """Follow a task: live lines, then the backbrief as a document with the decision on it.

    The backbrief is the artefact. When it is ready the person is not told to run another command; they are given
    the four choices the design specifies - approve, change a step's model, revise, cancel - plus detach, which
    leaves the task running. A pipe or a script never blocks on a prompt.
    """
    out = stream or sys.stdout
    ask = ask or _ask
    if interactive is None:
        interactive = sys.stdin.isatty()
    started, seen = time.time(), 0
    t = service.task(tid, store=store)
    print(header(t), file=out)
    last_status = t["status"]
    try:
        while True:
            t = service.task(tid, store=store)
            for line in t.get("events", [])[seen:]:
                print(paint(line), file=out)
            seen = len(t.get("events", []))
            if t["status"] != last_status:
                print(f"  → {label(t)}  {age(t.get('created'))}", file=out)
                last_status = t["status"]
            if t["status"] == "awaiting_gates":
                print(render_task(t), file=out)
                if not interactive:
                    print(f"Next: ariadne gates {tid} \"run: pytest -q\" \"README covers every command\"", file=out)
                    return 0
                print("Check gates: one per line, prefix a command with 'run:'. Blank line to finish.", file=out)
                gates = []
                while True:
                    line = (ask("gate > ") or "").strip()
                    if not line:
                        break
                    gates.append(line)
                if gates:
                    service.set_gates(tid, gates, store=store)
                    ensure_worker()
                    print(f"  {len(gates)} gate(s) set; planning", file=out)
                    continue
                print("  no gates, no start. ariadne gates <id> ... when you have them.", file=out)
                return 0
            if t["status"] == "awaiting_signoff":
                print(brief_view(t), file=out)
                if not interactive:
                    print(f"Next: ariadne ok {tid}   |   ariadne fix {tid} \"...\"   |   ariadne no {tid}", file=out)
                    return 0
                verdict = signoff(store, t, ask, out)
                if verdict in ("cancelled", "detached"):
                    return 0
                continue
            if t["status"] in WAITING or t["status"] in FINAL:
                print("", file=out)
                print(render_task(t), file=out)
                return 0
            if timeout and time.time() - started > timeout:
                print(f"\nstill {label(t)} after {age(started)}; detach and come back with: ariadne follow {tid}",
                      file=out)
                return 2
            time.sleep(poll)
    except KeyboardInterrupt:
        print(f"\n  detached. The task keeps running; ariadne shows what needs you.", file=out)
        return 0


def _models(rest) -> dict:
    out, i = {}, 0
    while i < len(rest):
        if rest[i] == "--model" and i + 1 < len(rest):
            for part in rest[i + 1].split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    out[k.strip()] = v.strip()
            i += 2
        else:
            i += 1
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd, rest = (argv[0], argv[1:]) if argv else ("inbox", [])
    rest = [a for a in rest if a != "--follow"]
    follow_after = "--follow" in argv
    try:
        store = service.store()
        if cmd == "inbox":
            print(inbox(store))
            return 0
        if cmd == "show":
            print(render_task(service.task(resolve(store, rest[0] if rest else ""), store=store)))
            return 0
        if cmd == "follow":
            return follow(store, resolve(store, rest[0] if rest else ""))
        if cmd == "ok":
            tid = resolve(store, rest[0] if rest else "")
            adopt(store, tid)
            service.approve(tid, _models(rest[1:]) or None, store=store)
            ensure_worker()
            after = service.task(tid, events=False, store=store)["status"]
            if after == "new":
                print(f"{tid}: approved. The plan did not fit, so it is planning again; a new backbrief follows.")
            else:
                print(f"{tid}: approved. The worker continues with the plan as it stands.")
            return follow(store, tid) if follow_after else 0
        if cmd == "fix":
            tid = resolve(store, rest[0] if rest else "")
            text = " ".join(a for a in rest[1:] if not a.startswith("--"))
            if not text:
                raise TaskError('say what to change: ariadne fix <id> "use pytest, not unittest"')
            adopt(store, tid)
            service.revise(tid, text, store=store)
            ensure_worker()
            print(f"{tid}: sent back to planning with your feedback.")
            return follow(store, tid) if follow_after else 0
        if cmd == "no":
            tid = resolve(store, rest[0] if rest else "")
            service.cancel(tid, store=store)
            print(f"{tid}: cancelled.")
            return 0
        if cmd == "gates":
            tid = resolve(store, rest[0] if rest else "")
            gates = [a for a in rest[1:] if not a.startswith("--")]
            if not gates:
                raise TaskError('list the gates: ariadne gates <id> "run: pytest -q" "README documents it"')
            service.set_gates(tid, gates, store=store)
            ensure_worker()
            print(f"{tid}: gates set; planning starts.")
            return follow(store, tid) if follow_after else 0
    except TaskError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"unknown command '{cmd}'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
