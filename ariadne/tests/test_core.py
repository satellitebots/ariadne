"""Unit tests for Ariadne's orchestrator, flows and shared memory (no models, no Hermes)."""
import json
from pathlib import Path

import pytest

from ariadne import flows as flowlib
from ariadne import models as modellib
from ariadne import orchestrator as orch
from ariadne import paths
from ariadne.memory import Memory, format_hits

REPO_FLOWS = paths.ROOT / "flows"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(paths, "STATE", tmp_path)
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)   # no weights in tests
    (tmp_path / "logs").mkdir()
    return tmp_path


# ---------- memory ----------

def test_memory_record_recall_and_links(env):
    m = Memory(env / "m.db")
    m.record("repo", "C:/repos/calc", "Python 3.12; tests live in tests/ and run with pytest")
    m.record("task", "t1", "fixed add() in calc", [("in_workspace", "repo", "C:/repos/calc")])
    hits = m.recall("how are tests run in calc")
    assert hits[0]["name"] == "C:/repos/calc"
    assert any("t1" in l for l in hits[0]["links"])          # incoming edge from the task
    m.record("repo", "C:/repos/calc", "Python 3.13 now")      # update in place, same node
    assert m.stats()["nodes"] == 2
    assert "3.13" in m.get("repo", "C:/repos/calc")["text"]
    assert "C:/repos/calc" in format_hits(m.recall("calc"))


def test_memory_is_durable_across_instances(env):
    Memory(env / "m.db").record("decision", "license", "MIT")
    assert Memory(env / "m.db").recall("license")[0]["text"] == "MIT"


def test_memory_ignores_empty_queries(env):
    assert Memory(env / "m.db").recall("  ?! ") == []


# ---------- flows ----------

def test_repo_flows_load_and_compile(env):
    fl = flowlib.load_flows(REPO_FLOWS)
    assert set(fl) == {"coding", "design", "writing", "content"}
    assert fl["coding"].status == "beta" and fl["design"].status == "experimental"
    home = flowlib.compile_flow(fl["coding"], REPO_FLOWS)
    cfg = (home / "config.yaml").read_text()
    assert "ariadne.memory_mcp" in cfg and "ariadne.git_mcp" in cfg and "ariadne_phase" in cfg
    assert (home / "skills" / "fix-and-verify" / "SKILL.md").exists()
    assert (home / "plugins" / "ariadne_phase" / "phase.py").exists()
    assert "git_status" in json.loads((home / "ariadne_flow.json").read_text())["plan_tools"]


def test_flow_validation(env, tmp_path):
    d = tmp_path / "flows" / "bad"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text("name: other\ndescription: x\nwhen: y\n")
    with pytest.raises(flowlib.FlowError, match="must match its folder"):
        flowlib.load_flows(tmp_path / "flows")
    (d / "flow.yaml").write_text("name: bad\ndescription: x\nwhen: y\nmcp_servers: [nope]\n")
    with pytest.raises(flowlib.FlowError, match="unknown MCP server"):
        flowlib.load_flows(tmp_path / "flows")


# ---------- orchestrator ----------

class FakeRunner:
    def __init__(self, plan="MISSION: fix it\nSTEPS:\n1. edit", results=("Changed add(); tests pass.",)):
        self.plan, self.results, self.calls = plan, list(results), []

    def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
        self.calls.append((flow.name, phase, prompt, model))
        if phase.startswith("checkpoint"):
            return orch.RunResult("SITUATION: x\nDONE: y", 0, "log", session or "h")
        if phase.startswith("learn"):
            name = f"{flow.name}-lessons"
            return orch.RunResult(f"Here it is.\n---\nname: {name}\ndescription: lessons\n---\n- keep tests green", 0, "log")
        text = self.plan if phase == "plan" else self.results.pop(0)
        return orch.RunResult(text, 0, "log")


def make_worker(env, runner, route_answer="coding", installer=None):
    flows = flowlib.load_flows(REPO_FLOWS)
    return orch.Worker(store=orch.Store(env / "t.db"), memory=Memory(env / "m.db"), flows=flows,
                       runner=runner, llm_chat=lambda model, msgs: route_answer,
                       installer=installer or (lambda name, cat, log=print: None), on_installed=lambda: None)


def test_full_drill_brief_backbrief_signoff_execute(env):
    run = FakeRunner()
    w = make_worker(env, run)
    tid = w.store.submit("fix the add bug", "test", str(env))
    assert w.run_once()                                     # route + plan
    t = w.store.get(tid)
    assert t["status"] == "awaiting_signoff" and t["flow"] == "coding" and "MISSION" in t["plan"]
    assert not w.run_once()                                 # nothing runs before sign-off
    w.store.approve(tid)
    assert w.run_once()                                     # execute
    t = w.store.get(tid)
    assert t["status"] == "done" and "tests pass" in t["result"]
    assert [c[1] for c in run.calls] == ["plan", "checkpoint:plan", "execute", "checkpoint:execute", "learn:execute"]
    # every finished task feeds the flow's learned skill, which every later run of the flow loads
    skill = paths.STATE / "skills" / "coding" / "coding-lessons" / "SKILL.md"
    assert skill.read_text().startswith("---\nname: coding-lessons") and "coding-lessons" in w.flows["coding"].learned_skills
    assert (w.flows["coding"].home / "skills" / "coding-lessons" / "SKILL.md").exists()
    # feedback after the report: recorded, and the worker rewrites the skill from it (the old one goes to history)
    w.store.feedback(tid, "use pathlib, not os.path")
    assert w.run_once() and "use pathlib" in run.calls[-1][2] and run.calls[-1][1] == "learn:execute"
    assert len(list((skill.parent / "history").glob("*.md"))) == 1
    assert not w.run_once()                                  # nothing left to learn
    assert "APPROVED PLAN" in run.calls[2][2] and "MISSION: fix it" in run.calls[2][2]
    assert run.calls[2][2].startswith("SESSION HANDOFF")      # execute starts from the plan's handoff brief
    assert "terminal" in run.calls[0][2] and "git (MCP)" in run.calls[0][2]   # planner knows the execute tools
    assert "done" in w.memory.get("task", tid)["text"]      # outcome is in shared memory
    assert any("route: coding" in e for e in t["events"])


def test_revise_replans_with_feedback(env):
    run = FakeRunner()
    w = make_worker(env, run)
    tid = w.store.submit("write a post", "test", str(env))
    w.run_once()
    w.store.revise(tid, "make it shorter")
    assert w.store.get(tid)["status"] == "new"
    w.run_once()
    assert "make it shorter" in run.calls[-1][2] and w.store.get(tid)["status"] == "awaiting_signoff"


def test_off_plan_goes_back_to_the_person(env):
    w = make_worker(env, FakeRunner(results=["OFF-PLAN: the file does not exist"]))
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once(); w.store.approve(tid); w.run_once()
    assert w.store.get(tid)["status"] == "needs_attention"
    w.store.revise(tid, "it is in src/")                    # person re-briefs; goes back to planning
    assert w.store.get(tid)["status"] == "new"


def test_failed_check_retries_once_then_reports(env):
    run = FakeRunner(results=["try 1", "try 2"])
    w = make_worker(env, run)
    w.flows["coding"].checks = ["exit 1"]
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once(); w.store.approve(tid); w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "failed" and "checks still failing" in t["error"]
    execs = [c for c in run.calls if c[1] == "execute"]
    assert "CHECKS FAILED" in execs[-1][2]                  # the retry was told what failed
    assert "QA RESULTS" in [c for c in run.calls if c[1].startswith("checkpoint")][-1][2]


def test_conditional_check_skipped_when_path_missing(env):
    w = make_worker(env, FakeRunner())
    w.flows["coding"].checks = [{"run": "exit 1", "when_exists": "tests"}]
    assert w.run_checks(w.flows["coding"], str(env)) == []


def test_router_answer_and_fallback(env):
    w = make_worker(env, FakeRunner(), route_answer="I think: writing")
    tid = w.store.submit("draft a memo", "test", str(env))
    assert w.route(w.store.get(tid))[0] == "writing"
    w.llm_chat = lambda m, msgs: "no idea"
    assert w.route(w.store.get(tid))[0] in w.flows        # falls back, never crashes


def test_sign_off_rules(env):
    st = orch.Store(env / "t.db")
    tid = st.submit("x", "test")
    with pytest.raises(orch.TaskError):
        st.approve(tid)                                     # nothing to approve yet
    st.cancel(tid)
    with pytest.raises(orch.TaskError):
        st.revise(tid, "no")
    with pytest.raises(orch.TaskError):
        st.submit("   ")


def test_worker_error_never_leaves_task_stuck(env):
    def boom(*a):
        raise RuntimeError("hermes missing")
    w = make_worker(env, boom)
    tid = w.store.submit("x", "test", str(env))
    w.run_once()
    assert w.store.get(tid)["status"] == "failed"


def test_wait_returns_when_backbrief_ready(env):
    w = make_worker(env, FakeRunner())
    tid = w.store.submit("fix", "test", str(env))
    w.run_once()
    assert w.store.wait(tid, timeout=2, poll=0.1)["status"] == "awaiting_signoff"


def test_clean_output_drops_tool_previews_and_session_lines():
    raw = ("\x1b[2m│\x1b[0m \x1b[1mcalc.py\x1b[0m\n│ -    return a - b\n"
           "Fixed calc.py; tests pass.\nSession ID: 20261117_abc\n")
    assert orch._clean_output(raw) == "Fixed calc.py; tests pass."
