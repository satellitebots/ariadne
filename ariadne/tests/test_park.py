import threading
import time

from ariadne import orchestrator as orch
from ariadne import park
from ariadne.tests.test_core import FakeRunner, make_worker, env  # noqa: F401 -- env is a fixture


def test_step_boundary_waits_for_a_finished_call(tmp_path):
    log = tmp_path / "logs" / "agent.log"
    log.parent.mkdir()
    log.write_text("old agent.conversation_loop: API call #1: model=x\n")
    b = park.StepBoundary(tmp_path)
    assert not b.reached()                       # starts watching from now; the old call does not count
    with open(log, "a") as f:
        f.write("12:00 INFO something else\n")
    assert not b.reached()
    with open(log, "a") as f:
        f.write("12:01 INFO agent.tool_executor: tool read_file completed (0.1s)\n")
    assert b.reached()


def test_a_parked_run_waits_for_resume_and_continues_the_same_session(env, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(park, "FLAG", tmp_path / "park.json")
    monkeypatch.setattr(park, "wait_resumed", lambda poll=0.05: _wait(poll))

    class Parks(FakeRunner):
        def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
            if phase == "execute" and not any(c[1] == "execute" for c in self.calls):
                self.calls.append((flow.name, phase, prompt, model, session))
                park.request("test")
                threading.Timer(0.3, park.resume).start()   # the person resumes a moment later
                return orch.RunResult("", orch.PARKED, "log", "hermes-123")
            self.calls.append((flow.name, phase, prompt, model, session))
            return orch.RunResult(self.plan if phase == "plan" else "done; tests pass", 0, "log", "h")

    run = Parks()
    w = make_worker(env, run)
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once(); w.store.approve(tid); w.run_once()
    execs = [c for c in run.calls if c[1] == "execute"]
    assert len(execs) == 2
    assert execs[1][4] == "hermes-123" and execs[1][2] == orch.RESUME_PROMPT   # same Hermes session, told to go on
    t = w.store.get(tid)
    assert t["status"] == "done"
    assert any("stopped at a step boundary" in e for e in t["events"]) and any("resumed" in e for e in t["events"])
    assert park.requested() is None


def test_a_run_out_of_turns_goes_to_the_gates(env, monkeypatch):  # noqa: F811
    class Turns(FakeRunner):
        def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
            self.calls.append((flow.name, phase, prompt, model, session))
            if phase == "execute" and sum(c[1] == "execute" for c in self.calls) == 1:
                return orch.RunResult("half done", 1, "log", "local-abc123def456")
            if phase.startswith("review"):
                return orch.RunResult("G1: PASS - seen", 0, "log")
            return orch.RunResult(self.plan if phase == "plan" else "done", 0, "log", "h")
    from ariadne import worker
    monkeypatch.setattr(worker, "_turn_end_reason", lambda home, sid: "max_iterations_reached" if sid else "")
    run = Turns()
    w = make_worker(env, run)
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once(); w.store.approve(tid); w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "done" and any("turn limit used up" in e for e in t["events"])


def _wait(poll):
    deadline = time.time() + 5
    while park.requested() and time.time() < deadline:
        time.sleep(poll)
