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
    assert set(fl) == {"coding", "design", "investigation", "content"}
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
        self.plan, self.results, self.calls, self.reviews = plan, list(results), [], []

    def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
        self.calls.append((flow.name, phase, prompt, model))
        if phase.startswith("checkpoint"):
            return orch.RunResult("SITUATION: x\nDONE: y", 0, "log", session or "h")
        if phase.startswith("review"):
            return orch.RunResult(self.reviews.pop(0) if self.reviews else "G1: PASS - seen", 0, "log")
        if phase.startswith("learn"):
            name = f"{flow.name}-lessons"
            return orch.RunResult(f"Here it is.\n---\nname: {name}\ndescription: lessons\n---\n- keep tests green", 0, "log")
        text = self.plan if phase == "plan" else self.results.pop(0)
        return orch.RunResult(text, 0, "log")


def make_worker(env, runner, route_answer="coding", installer=None):
    flows = flowlib.load_flows(REPO_FLOWS)
    return orch.Worker(store=orch.Store(env / "t.db", require_gates=False), memory=Memory(env / "m.db"), flows=flows,
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
    assert [c[1] for c in run.calls] == ["plan", "checkpoint:plan", "execute", "checkpoint:execute"]
    # local workers never write skills; feedback stays open until a larger model folds it into a shared skill
    w.store.feedback(tid, "use pathlib, not os.path")
    assert not w.run_once()
    assert w.store.open_feedback()[0]["task"] == tid and "use pathlib" in w.store.open_feedback()[0]["feedback"][-1]
    w.store.resolve_feedback([tid])
    assert w.store.open_feedback() == []
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


def test_failing_gates_iterate_and_stop_when_no_progress(env):
    run = FakeRunner(results=["try 1", "try 2", "try 3", "try 4"])
    w = make_worker(env, run)
    w.flows["coding"].checks = ["exit 1"]                    # never passes
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once(); w.store.approve(tid); w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "failed" and "no progress in the last two iterations" in t["error"]
    execs = [c for c in run.calls if c[1] == "execute"]
    assert len(execs) == 3                                  # stopped early, well before max_iterations (10)
    assert "GATES FAILED" in execs[-1][2]                   # each iteration was told what failed
    assert "QA RESULTS" in [c for c in run.calls if c[1].startswith("checkpoint")][-1][2]
    assert w.flows["coding"].max_iterations == 10


def test_a_timed_out_run_goes_to_the_gates_not_to_failed(env):
    class Slow(FakeRunner):
        def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
            r = super().__call__(flow, phase, prompt, ws, tid, model, session)
            return orch.RunResult("(timed out)", 124, "log") if phase == "execute" and len(self.calls) < 4 else r
    run = Slow(results=["unused", "done now"])
    w = make_worker(env, run)
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once(); w.store.approve(tid); w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "done" and any("run budget used up" in e for e in t["events"])


def test_shared_skills_are_validated_committed_and_loaded(env, monkeypatch, tmp_path):
    from ariadne import skills
    monkeypatch.setattr(skills, "SKILLS", tmp_path / "skills")
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "FLOWS_DIR", REPO_FLOWS)
    calls = []
    git = lambda *a: (calls.append(a), type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())[1]
    with pytest.raises(skills.SkillError):
        skills.save("coding", "py-style", "no frontmatter", git=git)
    report = skills.save("coding", "py-style", "---\nname: py-style\ndescription: Python style\n---\n- use pathlib",
                         note="from feedback on t1", git=git)
    assert "created" in report and "committed" in report and "pushed" in report
    assert calls[1][0] == "commit" and "Skill coding/py-style: from feedback on t1" in calls[1]
    assert calls[2] == ("push", "origin", "HEAD")
    assert skills.list_skills("coding") == [{"flow": "coding", "name": "py-style", "description": "Python style"}]
    fl = flowlib.load_flows(REPO_FLOWS)["coding"]
    assert fl.shared_skills == ["py-style"]


def test_no_task_starts_without_gates(env):
    st = orch.Store(env / "t.db")
    tid = st.submit("make it better", "test", str(env))
    t = st.get(tid)
    assert t["status"] == "awaiting_gates" and "check gates" in t["result"] and st.claim_next() is None
    st.revise(tid, "- run: pytest -q\n- README explains every command")   # the answer to the question
    t = st.get(tid)
    assert t["status"] == "new" and json.loads(t["gates"]) == [
        {"type": "run", "text": "pytest -q"}, {"type": "review", "text": "README explains every command"}]
    brief = "Build it.\n\nDone when:\n- `pytest -q` passes\n- every command is documented\n\nNotes: none"
    assert [g["type"] for g in orch.parse_gates(brief)] == ["run", "review"]
    assert st.get(st.submit(brief, "test"))["status"] == "new"


def test_review_gates_are_checked_by_a_reviewer_and_drive_iterations(env):
    run = FakeRunner(results=["try 1", "try 2"])
    run.reviews = ["G1: FAIL - README has no usage section", "G1: PASS - usage section present"]
    w = make_worker(env, run)
    w.store.require_gates = True
    tid = w.store.submit("write docs", "test", str(env), gates=["README has a usage section"])
    w.run_once()
    assert "README has a usage section" in run.calls[0][2]    # the planner sees the gates
    w.store.approve(tid); w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "done" and [c[1] for c in run.calls].count("execute") == 2
    assert "README has no usage section" in [c for c in run.calls if c[1] == "execute"][-1][2]
    assert any("iterate" in e for e in t["events"]) and any("review: 1/1 gates passed" in e for e in t["events"])


def test_conditional_check_skipped_when_path_missing(env):
    w = make_worker(env, FakeRunner())
    w.flows["coding"].checks = [{"run": "exit 1", "when_exists": "tests"}]
    assert w.run_checks(w.flows["coding"], str(env)) == []


def test_router_picks_an_approved_flow_and_rejects_otherwise(env):
    w = make_worker(env, FakeRunner(), route_answer="I think: investigation")
    tid = w.store.submit("compare two vendors", "test", str(env))
    assert w.route(w.store.get(tid))[0] == "investigation"
    w.llm_chat = lambda m, msgs: "no idea"
    assert w.route(w.store.get(tid))[0] is None            # rejected, never defaulted to the first flow


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


def test_activity_log_records_task_events_mcp_calls_and_worker_lines(env, monkeypatch):
    from ariadne import activity
    monkeypatch.setattr(activity, "LOG_DIR", env)
    st = orch.Store(env / "t.db", require_gates=False)
    tid = st.submit("x", "test")

    class Server:
        def tool(self):
            return lambda fn: fn
    srv = activity.instrument(Server(), "demo")

    @srv.tool()
    def add(a: int, b: int = 1) -> int:
        """Add."""
        return a + b
    assert add(2, b=3) == 5 and add.__doc__ == "Add."
    text = activity.log_file().read_text()
    assert f"[task {tid}] brief: from test: x" in text
    assert "[mcp:demo] add(2, b=3)" in text and "[mcp:demo] add done in" in text
    tool = ("2026-11-17 22:09:26,706 INFO [local-c6] agent.tool_executor: tool terminal completed (1.66s, 74 chars)")
    call = ("2026-11-17 17:11:13,260 INFO [local-6] agent.conversation_loop: API call #1: model=qwen3.5-9b provider=custom "
            "in=4033 out=206 total=4239 latency=4.9s cache=4008/4033 (99%) id=x")
    assert activity._hermes_line("coding", tool) == "22:09:26 [coding] tool terminal completed (1.66s, 74 chars)"
    assert activity._hermes_line("coding", call) == ("17:11:13 [coding] model qwen3.5-9b call 1: 4033 tokens in, 206 out, "
                                                     "4.9s, cached 4008/4033")
    # one file per day, the two newest kept
    for day in ("2026-11-14", "2026-11-15", "2026-11-16"):
        activity.log_file(day).write_text("old\n")
    activity.log_file().unlink()
    activity.log("test", "new day")
    assert sorted(f.name for f in env.glob("activity-*.log"))[0] == "activity-2026-11-16.log"
    assert len(list(env.glob("activity-*.log"))) == 2
