"""B1: the task wall-clock and `timed_out` - a terminal status, proved without a model.

The contract (docs/COVERAGE.md, "Three timeout levels"): a task that spends its `task_budget` stops running, keeps
what was written, and the gates that need no model decide. Passing gates still make it `done`; anything left ends
`timed_out`, which is terminal and reaches the caller.
"""
import sqlite3
import time

import pytest

from ariadne import flows as flowlib
from ariadne import models as modellib
from ariadne import orchestrator as orch
from ariadne import paths, present, service, tasks_mcp
from ariadne.memory import Memory

REPO_FLOWS = paths.ROOT / "flows"
PLAN = ("MISSION: the leap-year test passes\n\nSTEPS:\n1. fix parse_date() - model: qwen3.6-35b-a3b\n\n"
        "```json\n"
        '{"mission": "the leap-year test passes", "steps": [{"n": 1, "text": "fix parse_date()"}],\n'
        ' "gates": ["G1: step 1 makes it pass"], "risks": [], "questions": []}\n'
        "```")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(paths, "STATE", tmp_path)
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)   # no weights in tests
    (tmp_path / "logs").mkdir()
    return tmp_path


class Clock:
    """Time a test can spend. It starts at the real clock so `run_started` and the budget share one timebase."""

    def __init__(self, start=None):
        self.t = time.time() if start is None else start

    def __call__(self):
        return self.t

    def spend(self, seconds):
        self.t += seconds


class FakeRunner:
    """The plan, then one answer per execute run. `spend` is charged to the clock when execute returns."""

    def __init__(self, clock=None, spend=0, results=("Changed calc.py; tests pass.",)):
        self.clock, self.spend, self.results, self.calls = clock, spend, list(results), []

    def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
        self.calls.append((flow.name, phase, prompt, model))
        if phase.startswith("checkpoint"):
            return orch.RunResult("SITUATION: x\nDONE: y", 0, "log", "h1")
        if phase.startswith("review"):
            return orch.RunResult("G1: PASS - seen", 0, "log")
        if phase == "plan":
            return orch.RunResult(PLAN, 0, "log")
        if self.clock and self.spend:
            self.clock.spend(self.spend)
        return orch.RunResult(self.results.pop(0) if self.results else "done", 0, "log")


def make_worker(env, runner, clock=None):
    return orch.Worker(store=orch.Store(env / "t.db", require_gates=False), memory=Memory(env / "m.db"),
                       flows=flowlib.load_flows(REPO_FLOWS), runner=runner, llm_chat=lambda m, msgs: "coding",
                       installer=lambda name, cat, log=print: None, on_installed=lambda: None, clock=clock)


def brief(env, w, gates, budget=None):
    """Submit, plan, sign off; returns the id, ready for execute."""
    if budget is not None:
        w.flows["coding"].task_budget = budget
    tid = w.store.submit("fix the leap year test", "test", str(env), gates=gates)
    assert w.run_once(), "the plan should have run"
    assert w.store.get(tid)["status"] == "awaiting_signoff"
    w.store.approve(tid)
    return tid


def test_timed_out_is_a_terminal_status_in_every_surface(env, monkeypatch):
    st = orch.Store(env / "t.db", require_gates=False)
    monkeypatch.setattr(service, "_store", st)
    monkeypatch.setattr(tasks_mcp, "store", lambda: st)
    tid = st.submit("x", "test", str(env))
    st.update(tid, status="timed_out", result="ran out of time", error="wall clock spent")
    t = st.get(tid)
    assert "timed_out" in orch.FINAL and "timed_out" not in orch.WAITING
    assert present.STATUS["timed_out"] == "out of time" and present.MARK["timed_out"] == "\u23f1"
    assert present.view(t)["label"] == "out of time" and present.view(t)["actions"] == []
    assert st.wait(tid, timeout=2, poll=0.01)["status"] == "timed_out"      # the callback returns at once
    assert tid in [r["id"] for r in service.inbox()["recent"]]
    card = tasks_mcp._view(t)
    assert "out of time" in card and "wall-clock budget" in card


def test_wall_clock_spent_keeps_the_work_and_lets_the_gates_decide(env):
    clock = Clock()
    run = FakeRunner(clock=clock, spend=3600)
    w = make_worker(env, run, clock=clock)
    tid = brief(env, w, ["run: exit 0"], budget=600)
    assert w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "done" and "Changed calc.py" in t["result"]      # what was written is kept
    assert "Ran out of its 600 s wall clock" in t["result"]
    assert any("wall clock spent" in e for e in t["events"])
    assert [c[1] for c in run.calls].count("execute") == 1                 # no further model work
    assert not [c for c in run.calls if c[1].startswith("review")]         # the reviewer is exactly what ran out


def test_wall_clock_spent_with_a_failing_gate_ends_timed_out(env):
    clock = Clock()
    w = make_worker(env, FakeRunner(clock=clock, spend=3600), clock=clock)
    tid = brief(env, w, ["run: exit 1"], budget=600)
    assert w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "timed_out" and "Changed calc.py" in t["result"]
    assert "FAILING GATES" in t["result"] and "600 s wall clock" in t["error"]
    assert any("timeout:" in e for e in t["events"])


def test_a_review_gate_out_of_time_is_named_not_guessed(env):
    clock = Clock()
    w = make_worker(env, FakeRunner(clock=clock, spend=3600), clock=clock)
    tid = brief(env, w, ["README explains every command"], budget=600)
    assert w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "timed_out" and "NOT REVIEWED" in t["result"]
    assert "README explains every command" in t["result"]                  # the person knows what is left
    assert not [c for c in w.runner.calls if c[1].startswith("review")]


def test_no_task_budget_means_no_task_level_limit(env):
    clock = Clock()
    w = make_worker(env, FakeRunner(clock=clock, spend=10 ** 6), clock=clock)
    tid = brief(env, w, ["run: exit 0"], budget=0)
    assert w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "done" and not any("wall clock spent" in e for e in t["events"])


def test_waiting_for_sign_off_does_not_spend_the_wall_clock(env):
    """The budget is worker time: a brief that sits overnight is not timed out the moment it is approved."""
    clock = Clock()
    w = make_worker(env, FakeRunner(clock=clock), clock=clock)
    w.flows["coding"].task_budget = 600
    tid = w.store.submit("fix the leap year test", "test", str(env), gates=["run: exit 0"])
    w.run_once()
    clock.spend(10 ** 6)                                                   # the person is asleep for 11 days
    w.store.approve(tid)
    w.run_once()
    assert w.store.get(tid)["status"] == "done"


def test_every_approved_flow_sets_a_task_wall_clock():
    flows = flowlib.load_flows(REPO_FLOWS)
    assert set(flows) == {"coding", "design", "investigation", "content"}
    assert all(f.task_budget > 0 for f in flows.values())


def test_an_old_store_gains_the_wall_clock_column(env):
    db = env / "old.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, created REAL, updated REAL, source TEXT, text TEXT, "
              "workspace TEXT, flow TEXT, status TEXT, plan TEXT DEFAULT '', feedback TEXT DEFAULT '', "
              "result TEXT DEFAULT '', error TEXT DEFAULT '', models TEXT DEFAULT '', session TEXT DEFAULT '', "
              "learn INTEGER DEFAULT 0, gates TEXT DEFAULT '', model TEXT DEFAULT '', plan_json TEXT DEFAULT '')")
    c.execute("CREATE TABLE events(task_id TEXT, ts REAL, kind TEXT, detail TEXT)")
    c.execute("CREATE TABLE sessions(name TEXT PRIMARY KEY, created REAL, updated REAL, source TEXT DEFAULT '', "
              "segment INTEGER DEFAULT 1, flow TEXT DEFAULT '', summary TEXT DEFAULT '', fresh INTEGER DEFAULT 0, "
              "dirty INTEGER DEFAULT 0)")
    c.commit()
    c.close()
    orch.Store(db)
    cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(tasks)")]
    assert "run_started" in cols
