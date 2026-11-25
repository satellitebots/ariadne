import sys
import threading
import time
from pathlib import Path

import pytest

from ariadne import durable, engine, flows as flowlib, jobs, park, spec as speclib
from ariadne.broker import Broker
from ariadne.tests.test_broker import FakeServer
from ariadne.engine import RunResult

FLOWS = flowlib.load_flows()
PY = f'"{sys.executable}"'


def make_spec(ws, steps, gates=(), retries=1):
    return speclib.validate({"name": "t-one", "flow": "investigation", "goal": "a report", "workspace": str(ws),
                             "steps": steps, "gates": list(gates), "retries": retries, "trigger": {"kind": "manual"}},
                            FLOWS)


class Script:
    """A fake worker: `plan` maps (kind, step n or 'review') to a list of callables run in turn; each gets the
    workspace and the prompt and returns (text, exit_code)."""
    def __init__(self, plan):
        self.plan, self.calls = {k: list(v) for k, v in plan.items()}, []

    def __call__(self, flow, kind, prompt, ws, ref, model, tools, session=None, **kw):
        n = "review" if kind == "review" else int(prompt.split("STEP ", 1)[1].split(" ", 1)[0]) if "STEP " in prompt \
            else self.calls[-1][1]
        self.calls.append((kind, n, prompt, session, tools))
        fn = self.plan[n].pop(0) if self.plan.get(n) else (lambda ws, p: ("done", 0))
        text, code = fn(Path(ws), prompt)
        return RunResult(text, code, "log", f"sess-{n}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(park, "FLAG", tmp_path / "park.json")
    store = durable.Store(tmp_path / "a.db")
    server = FakeServer()
    broker = Broker(tmp_path / "m.db", server=server, poll=0.01)
    return store, broker, server, tmp_path


def start(store, sp):
    tid, _ = store.sign(sp)
    return store.run_new(tid)


def write(name, text="x"):
    def f(ws, prompt):
        (ws / name).write_text(text, encoding="utf-8")
        return f"wrote {name}", 0
    return f


def test_steps_run_in_order_hand_over_files_and_pass_gates(env):
    store, broker, server, tmp = env
    ws = tmp / "ws"
    sp = make_spec(ws, [{"title": "A", "instruction": "make a", "outputs": ["a.txt"]},
                        {"title": "B", "instruction": "make b", "outputs": ["b.txt"],
                         "gate": {"type": "run", "text": f"{PY} -c \"import os,sys; sys.exit(0 if os.path.exists('b.txt') else 1)\""}}],
                   gates=[{"type": "review", "text": "b says hi"}])
    rid = start(store, sp)
    script = Script({1: [write("a.txt")], 2: [write("b.txt", "hi")], "review": [lambda ws, p: ("PASS - b.txt says hi", 0)]})
    e = engine.Engine(store, FLOWS, broker, step_runner=script)
    assert e.run_once()
    r = store.run(rid)
    assert r["status"] == "done", r["error"]
    step2 = next(c for c in script.calls if c[1] == 2)
    assert "a.txt" in step2[2] and "forward slashes" in step2[2]          # inputs named; bash path rule given
    assert f"TODAY: {time.strftime('%A')}" in step2[2] or "TODAY: " in step2[2]  # the worker knows the date (task tz)
    assert broker.holder() is None                                          # the machine is given back


def test_a_new_run_starts_clean_and_keeps_the_last_outputs(env):
    store, broker, server, tmp = env
    ws = tmp / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("from the last run", encoding="utf-8")
    sp = make_spec(ws, [{"title": "A", "instruction": "make a", "outputs": ["a.txt"]}])
    rid = start(store, sp)
    seen = []

    def check(ws_, prompt):
        seen.append((ws_ / "a.txt").exists())
        return write("a.txt", "new")(ws_, prompt)

    engine.Engine(store, FLOWS, broker, step_runner=Script({1: [check]})).run_once()
    assert seen == [False] and store.run(rid)["status"] == "done"
    old = list((ws / ".history").rglob("a.txt"))
    assert len(old) == 1 and old[0].read_text(encoding="utf-8") == "from the last run"


def test_a_failing_check_retries_with_the_reasons_then_needs_you(env):
    store, broker, server, tmp = env
    sp = make_spec(tmp / "ws", [{"title": "A", "instruction": "make a", "outputs": ["a.txt"]}], retries=1)
    rid = start(store, sp)
    script = Script({1: [lambda ws, p: ("forgot", 0), lambda ws, p: ("forgot again", 0)]})
    engine.Engine(store, FLOWS, broker, step_runner=script).run_once()
    r = store.run(rid)
    assert r["status"] == "needs_you" and "still fails after 2 attempt" in r["error"]
    assert "a.txt is missing" in script.calls[1][2]                          # the retry is told what failed
    assert [s["status"] for s in store.steps(rid)] == ["failed", "failed"]


def test_a_job_gets_the_whole_machine_and_wakes_the_same_session(env):
    store, broker, server, tmp = env
    sp = make_spec(tmp / "ws", [{"title": "A", "instruction": "pull data", "outputs": ["data.txt"]}])
    rid = start(store, sp)
    server.call("qwen")

    def submit(ws, prompt):
        jobs.submit(rid, f"{PY} -c \"open('data.txt','w').write('42')\"", ws, why="pull")
        return "JOB SUBMITTED", 0

    script = Script({1: [submit, lambda ws, p: ("data.txt has 42", 0)]})
    engine.Engine(store, FLOWS, broker, step_runner=script).run_once()
    assert store.run(rid)["status"] == "done", store.run(rid)["error"]
    assert "unload" in server.calls
    woke = script.calls[1]
    assert woke[3] == "sess-1" and "JOB" in woke[2] and "DONE" in woke[2]


def test_park_steer_resume_continues_the_same_session(env):
    store, broker, server, tmp = env
    sp = make_spec(tmp / "ws", [{"title": "A", "instruction": "make a", "outputs": ["a.txt"]}])
    rid = start(store, sp)

    def parked(ws, prompt):
        park.request("test")
        store.steer(rid, "use weekly bars")
        threading.Timer(0.2, park.resume).start()
        return "", engine.PARKED

    script = Script({1: [parked, write("a.txt")]})
    seen = []
    e = engine.Engine(store, FLOWS, broker, step_runner=script,
                      wait_resumed=lambda: (seen.append(broker.holder()), park.wait_resumed(0.05)))
    e.run_once()
    assert store.run(rid)["status"] == "done"
    assert seen == [None]                                                     # parked = the machine was free
    resumed = script.calls[1]
    assert resumed[3] == "sess-1" and "use weekly bars" in resumed[2]


def test_cancel_stops_at_the_boundary(env):
    store, broker, server, tmp = env
    sp = make_spec(tmp / "ws", [{"title": "A", "instruction": "a"}, {"title": "B", "instruction": "b"}])
    rid = start(store, sp)

    def then_cancel(ws, prompt):
        store.run_set(rid, error="cancel requested")
        return "did a", 0

    engine.Engine(store, FLOWS, broker, step_runner=Script({1: [then_cancel]})).run_once()
    assert store.run(rid)["status"] == "cancelled"


def test_the_scheduler_queues_due_tasks_once(env):
    store, broker, server, tmp = env
    sp = make_spec(tmp / "ws", [{"title": "A", "instruction": "a"}])
    sp["trigger"] = {"kind": "cron", "cron": "0 7 * * *"}
    tid, _ = store.sign(sp)
    due = store.task(tid)["next_due"]
    clock = [due + 3 * 86400]          # three missed mornings
    e = engine.Engine(store, FLOWS, broker, step_runner=Script({}), clock=lambda: clock[0])
    assert len(e.sweep()) == 1                                              # once, not three times
    assert store.task(tid)["next_due"] > clock[0]
    assert e.sweep() == []
