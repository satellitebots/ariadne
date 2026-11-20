"""B4: one Hermes session per task, gates at the edge, and a failed gate resumes that same session.

The plan is data (`models.chain`): consecutive steps one agent model owns share a session, and only a model change
starts another one, with a carry-forward note. Nothing here needs a model: the runner is a fake that records the
session it was asked to resume.
"""
import json

import pytest

from ariadne import flows as flowlib
from ariadne import orchestrator as orch
from ariadne import worker
from ariadne.memory import Memory
from ariadne.tests.test_core import REPO_FLOWS, env  # noqa: F401 -- env is a fixture

ONE = ('MISSION: the test passes\n\n```json\n'
       '{"mission": "the test passes", "steps": [{"n": 1, "text": "fix parse_date()"}], "gates": [], "risks": [], '
       '"questions": []}\n```')
THREE = ('MISSION: two models\n\n```json\n'
         '{"mission": "two models", "steps": [{"n": 1, "text": "a", "model": "qwen3.6-35b-a3b"}, '
         '{"n": 2, "text": "b", "model": "gemma-4-12b"}, {"n": 3, "text": "c", "model": "gemma-4-12b"}], '
         '"gates": [], "risks": [], "questions": []}\n```')


class SessionRunner:
    """Records the session each run was asked to resume; gives every execute run a fresh session id."""

    def __init__(self, plan=ONE):
        self.plan, self.calls, self.n = plan, [], 0

    def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
        self.calls.append({"phase": phase, "prompt": prompt, "session": session, "model": model})
        if phase == "plan":
            return orch.RunResult(self.plan, 0, "log", "p1")
        if phase.startswith("checkpoint"):
            return orch.RunResult("SITUATION: x\nDONE: y", 0, "log", session or "c1")
        if phase.startswith("review"):
            return orch.RunResult("G1: PASS - seen", 0, "log")
        self.n += 1
        return orch.RunResult(f"attempt {self.n}", 0, "log", f"s{self.n}")


def make(env, run, **kw):
    return orch.Worker(store=orch.Store(env / "t.db", require_gates=False), memory=Memory(env / "m.db"),
                       flows=flowlib.load_flows(REPO_FLOWS), runner=run, llm_chat=lambda m, msgs: "coding",
                       installer=lambda name, cat, log=print: None, on_installed=lambda: None, **kw)


def drill(env, run, gates, **kw):
    w = make(env, run, **kw)
    tid = w.store.submit("fix the leap year test", "test", str(env), gates=gates)
    assert w.run_once()
    w.store.approve(tid)
    assert w.run_once()
    return w, tid


def test_a_failed_gate_resumes_the_same_session(env):  # noqa: F811
    run = SessionRunner()
    w = make(env, run)
    answers = [["G1 [run] exit 1"], []]
    w.qa = lambda t, flow, ws, model: answers.pop(0)          # first round fails, the second passes
    tid = w.store.submit("fix the leap year test", "test", str(env), gates=["run: exit 1"])
    w.run_once()
    w.store.approve(tid)
    w.run_once()
    execs = [c for c in run.calls if c["phase"] == "execute"]
    assert len(execs) == 2
    assert execs[0]["session"] is None                         # the first run opens the session
    assert execs[1]["session"] == "s1"                         # the second resumes it - not a fresh one
    assert execs[1]["prompt"].startswith("GATES FAILED") and "G1 [run] exit 1" in execs[1]["prompt"]
    # one session, gates at the edge: compression once after the plan, once when QA passes - never between attempts
    assert [c["phase"] for c in run.calls if c["phase"].startswith("checkpoint")] == \
        ["checkpoint:plan", "checkpoint:execute"]
    t = w.store.get(tid)
    assert t["status"] == "done" and "attempt 2" in t["result"]     # the report is the round that passed
    assert any("attempt 1" in e for e in t["events"]) and any("attempt 2" in e for e in t["events"])


def test_a_plan_that_changes_agent_model_is_a_recorded_chain(env):  # noqa: F811
    run = SessionRunner(plan=THREE)
    w, tid = drill(env, run, gates=["run: exit 0"])
    t = w.store.get(tid)
    assert t["status"] == "done", t["error"] or t["result"]
    mp = json.loads(t["models"])
    assert [(c["agent"], c["steps"]) for c in mp["chain"]] == [("qwen3.6-35b-a3b", [1]), ("gemma-4-12b", [2, 3])]
    assert "2 sessions (a session per agent model" in t["plan"]
    execs = [c for c in run.calls if c["phase"] == "execute"]
    assert [c["model"] for c in execs] == ["qwen3.6-35b-a3b", "gemma-4-12b"]
    assert execs[1]["prompt"].startswith("SESSION HANDOFF")     # the carry-forward note
    assert "NOW DO STEPS 2, 3 ONLY" in execs[1]["prompt"]


def test_a_model_override_rewrites_the_recorded_chain(env):  # noqa: F811
    from ariadne import models as modellib
    cat = modellib.load()
    mp = {"agent": "qwen3.6-35b-a3b", "notes": [], "steps": [
        {"n": 1, "text": "a", "model": "qwen3.6-35b-a3b"},
        {"n": 2, "text": "b", "model": "qwen3.6-35b-a3b"}]}
    mp["chain"] = worker.chain_for(mp, cat)
    assert [c["steps"] for c in mp["chain"]] == [[1, 2]]
    mp = worker.apply_model_overrides(mp, "2=gemma-4-12b")
    assert [(c["agent"], c["steps"]) for c in mp["chain"]] == [("qwen3.6-35b-a3b", [1]), ("gemma-4-12b", [2])]


def test_execution_lives_in_worker_not_orchestrator():
    assert worker.chain_for and worker.Worker and worker.RETRY_PROMPT
    assert not hasattr(orch, "step_groups") and not hasattr(orch, "agent_for")
    assert orch.Worker is worker.Worker                        # the old import path still resolves
