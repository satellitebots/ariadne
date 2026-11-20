"""Tests for the control-plane discrepancies fixed across the design passes (no models, no Hermes, no GPU)."""
import io
import json
import subprocess

import pytest

from ariadne import console
from ariadne import flows as flowlib
from ariadne import models as modellib
from ariadne import orchestrator as orch
from ariadne import paths
from ariadne.memory import Memory

REPO_FLOWS = paths.ROOT / "flows"

TWO_GROUP_PLAN = """MISSION: fix the add bug and prove it
STEPS:
1. edit calc.py - tools: file - model: qwen3.8-27b
2. run the tests - tools: terminal - model: qwen3.6-35b-a3b
GATES: G1 by step 2
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    from ariadne import models as modellib
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(paths, "STATE", tmp_path)
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)   # no weights in tests
    monkeypatch.setattr(console, "ensure_worker", lambda: False)          # never spawn a real worker
    (tmp_path / "logs").mkdir()
    return tmp_path


class FakeRunner:
    def __init__(self, plan="MISSION: fix it\nSTEPS:\n1. edit", results=("done",)):
        self.plan, self.results, self.calls = plan, list(results), []

    def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
        self.calls.append((flow.name, phase, prompt, model))
        if phase.startswith("checkpoint"):
            return orch.RunResult("SITUATION: x", 0, "log", session or "h")
        if phase.startswith("review"):
            return orch.RunResult("G1: PASS - seen", 0, "log")
        return orch.RunResult(self.plan if phase == "plan" else self.results.pop(0), 0, "log")


def make_worker(env, runner):
    return orch.Worker(store=orch.Store(env / "t.db", require_gates=False),
                       memory=Memory(env / "m.db"), flows=flowlib.load_flows(REPO_FLOWS),
                       runner=runner, llm_chat=lambda m, msgs: "coding",
                       installer=lambda name, cat, log=print: None, on_installed=lambda: None)


def test_out_of_time_on_an_early_group_is_not_a_failure(env):
    """The turn/run-budget tolerance used to apply only to the last step group (B1)."""
    class EarlyTimeout(FakeRunner):
        def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
            r = super().__call__(flow, phase, prompt, ws, tid, model, session)
            if phase == "execute" and model == "qwen3.8-27b":
                return orch.RunResult("half of the edit is in the file", 124, "log", "s1")
            return r

    run = EarlyTimeout(plan=TWO_GROUP_PLAN, results=("tests pass", "unused"))
    w = make_worker(env, run)
    tid = w.store.submit("fix the add bug", "test", str(env))
    w.run_once()
    assert len(orch.chain_for(json.loads(w.store.get(tid)["models"]), w.catalog)) == 2
    w.store.approve(tid)
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "done", t["error"] or t["result"]
    assert any("run budget used up on steps 1" in e for e in t["events"])
    # what the timed-out group wrote is carried forward instead of being replaced by a synthetic sentence
    assert "half of the edit is in the file" in t["result"]


def test_unknown_flow_key_is_refused(env, tmp_path):
    d = tmp_path / "flows" / "typo"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text("name: typo\ndescription: x\nwhen: y\nmax_turn: {plan: 5}\n")
    with pytest.raises(flowlib.FlowError, match="unknown key"):
        flowlib.load_flows(tmp_path / "flows")


def test_unknown_nested_flow_key_is_refused(env, tmp_path):
    d = tmp_path / "flows" / "typo"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text("name: typo\ndescription: x\nwhen: y\ntoolsets: {plan: [file], excute: [file]}\n")
    with pytest.raises(flowlib.FlowError, match="under 'toolsets'"):
        flowlib.load_flows(tmp_path / "flows")


def test_worker_start_hands_back_orphaned_tasks(env):
    st = orch.Store(env / "t.db", require_gates=False)
    tid = st.submit("was running when the PC crashed", "test", str(env))
    st.update(tid, status="executing")
    orch._reconcile(st)
    t = st.get(tid)
    assert t["status"] == "needs_attention" and "worker restarted" in t["result"]
    assert any("recover" in e for e in t["events"])


# ---------- the model-free surface ----------

def test_render_task_is_readable_and_never_raw_json(env):
    st = orch.Store(env / "t.db", require_gates=False)
    tid = st.submit("Add a --verbose flag", "cli", str(env), gates=["run: pytest -q", "README documents the flag"])
    st.update(tid, status="awaiting_signoff", plan="MISSION: the flag works\nSTEPS:\n1. edit cli.py")
    text = console.render_task(st.get(tid))
    assert "Check gates" in text and "G1  [run]  pytest -q" in text and "G2  [review]" in text
    assert "Backbrief" in text and "MISSION: the flag works" in text
    assert text.rstrip().endswith(f"Next: ariadne ok {tid}   |   ariadne fix {tid} \"what to change\"   |   "
                                  f"ariadne no {tid}")
    assert "\\n" not in text          # the old output was a JSON blob with escaped newlines


def test_inbox_says_what_needs_you(env):
    st = orch.Store(env / "t.db", require_gates=False)
    waiting = st.submit("needs a decision", "cli", str(env), gates=["run: true"])
    st.update(waiting, status="awaiting_signoff", plan="MISSION: x")
    queued = st.submit("still working", "cli", str(env), gates=["run: true"])
    st.update(queued, status="approved")
    text = console.inbox(st)
    assert "NEEDS YOU (1)" in text and waiting in text
    assert "QUEUED / RUNNING (1)" in text and queued in text


def test_inbox_calls_out_a_task_with_no_worker_behind_it(env):
    """A crash leaves rows in planning/executing. Silence is what let one read 'executing' for two days."""
    st = orch.Store(env / "t.db", require_gates=False)
    tid = st.submit("was running when the PC crashed", "cli", str(env), gates=["run: true"])
    st.update(tid, status="executing")
    text = console.inbox(st)
    assert "STOPPED, NO WORKER (1)" in text and tid in text
    assert "QUEUED / RUNNING" not in text


def test_an_orphaned_task_is_adopted_then_can_be_approved(env):
    st = orch.Store(env / "t.db", require_gates=False)
    tid = st.submit("was running when the PC crashed", "cli", str(env), gates=["run: true"])
    st.update(tid, status="executing")
    assert "no worker is running" in console.render_task(st.get(tid))
    with pytest.raises(orch.TaskError):        # approval is refused while the row is still 'executing'
        st.approve(tid)
    console.adopt(st, tid)
    assert st.get(tid)["status"] == "needs_attention"
    st.approve(tid)                            # and now the person can continue it
    assert st.get(tid)["status"] == "approved"


def test_approving_an_off_plan_stop_replans_instead_of_rerunning(env):
    """The lifecycle diagram's "stuck or off-plan -> backbrief" branch: a new plan, not the old one again."""
    run = FakeRunner(results=["OFF-PLAN: the file the plan names does not exist"])
    w = make_worker(env, run)
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once(); w.store.approve(tid); w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "needs_attention" and t["error"] == "off-plan"
    w.store.approve(tid)
    t = w.store.get(tid)
    assert t["status"] == "new" and t["error"] == ""
    w.run_once()
    assert w.store.get(tid)["status"] == "awaiting_signoff"


def test_workspace_changes_reads_git_without_a_model(tmp_path):
    from ariadne import workspace

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init")
    (repo / "a.txt").write_text("one", encoding="utf-8")
    git("add", "a.txt")
    git("-c", "user.email=a@b", "-c", "user.name=t", "commit", "-m", "first")
    (repo / "a.txt").write_text("two", encoding="utf-8")
    out = workspace.changes(str(repo))
    assert out["git"] is True and any("a.txt" in f for f in out["files"])
    assert "a.txt" in out["stat"]
    assert workspace.changes(str(tmp_path / "missing"))["note"] == "workspace not found"


def test_resolve_takes_a_prefix_or_the_only_waiting_task(env):
    st = orch.Store(env / "t.db", require_gates=False)
    first = st.submit("a", "cli", str(env), gates=["run: true"])
    st.update(first, status="awaiting_signoff")
    assert console.resolve(st, first[:6]) == first      # a unique prefix
    assert console.resolve(st, "") == first             # the only one that needs a person
    second = st.submit("b", "cli", str(env), gates=["run: true"])
    st.update(second, status="needs_attention")
    with pytest.raises(orch.TaskError, match="several tasks need you"):
        console.resolve(st, "")


def test_status_exposes_what_needs_a_person(env, monkeypatch):
    from ariadne import park
    st = orch.Store(env / "t.db", require_gates=False)
    tid = st.submit("review me", "cli", str(env), gates=["run: true"])
    st.update(tid, status="awaiting_signoff")
    out = park.status(store=st)
    assert [n["id"] for n in out["needs"]] == [tid]


# ---------- the workflow: the backbrief is the artefact ----------

PLAN = """MISSION: the leap-year test passes
STEPS:
1. fix parse_date() for Feb 29 - tools: file - model: qwen3.6-35b-a3b
2. add leap-year tests - tools: terminal - model: qwen3.6-35b-a3b
GATES: G1 by step 2
RISKS: none
QUESTIONS: none
"""

MODELS = {"agent": "qwen3.6-35b-a3b",
          "steps": [{"n": 1, "text": "fix parse_date() for Feb 29 - tools: file - model: qwen3.6-35b-a3b",
                     "model": "qwen3.6-35b-a3b"},
                    {"n": 2, "text": "add leap-year tests - tools: terminal - model: qwen3.6-35b-a3b",
                     "model": "qwen3.6-35b-a3b"}]}


def _backbrief_task(env):
    st = orch.Store(env / "t.db", require_gates=False)
    tid = st.submit("fix the leap year test", "cli", str(env), gates=["run: pytest -q"])
    st.update(tid, status="awaiting_signoff", plan=PLAN, models=json.dumps(MODELS))
    return st, tid


def test_brief_view_is_the_document_not_a_field(env):
    st, tid = _backbrief_task(env)
    view = console.brief_view(st.get(tid, events=False))
    assert "BACKBRIEF" in view
    assert "MISSION  the leap-year test passes" in view
    assert "fix parse_date() for Feb 29" in view and "qwen3.6-35b-a3b" in view
    assert "tools: file" not in view            # the tail becomes a column, not part of the sentence
    assert "CHECKS" in view and "G1 [run] pytest -q" in view
    assert "{" not in view                      # never a JSON blob


def test_signoff_is_taken_on_the_backbrief(env):
    st, tid = _backbrief_task(env)
    out = io.StringIO()
    assert console.signoff(st, st.get(tid, events=False), ask=lambda p: "a", out=out) == "approved"
    assert st.get(tid, events=False)["status"] == "approved"


def test_signoff_can_change_one_steps_model(env):
    st, tid = _backbrief_task(env)
    answers = iter(["m", "2", "1"])          # step 2, first agent model in the approved catalog
    out = io.StringIO()
    assert console.signoff(st, st.get(tid, events=False), ask=lambda p: next(answers), out=out) == "approved"
    t = st.get(tid, events=False)
    assert t["status"] == "approved" and "qwen3.8-27b" in t["models"]
    assert "[1] qwen3.8-27b" in out.getvalue()      # the choices are a numbered list, not a guess


def test_signoff_revise_and_detach(env):
    st, tid = _backbrief_task(env)
    out = io.StringIO()
    assert console.signoff(st, st.get(tid, events=False), ask=lambda p: "d", out=out) == "detached"
    assert st.get(tid, events=False)["status"] == "awaiting_signoff"     # nothing changed
    answers = iter(["r", "use pytest, not unittest"])
    assert console.signoff(st, st.get(tid, events=False), ask=lambda p: next(answers), out=out) == "revised"
    t = st.get(tid, events=False)
    assert t["status"] == "new" and "use pytest" in t["feedback"]


def test_follow_renders_the_backbrief_and_never_blocks_without_a_tty(env):
    st, tid = _backbrief_task(env)
    out = io.StringIO()
    assert console.follow(st, tid, poll=0.01, stream=out, interactive=False) == 0
    text = out.getvalue()
    assert "session" in text and "BACKBRIEF" in text and "MISSION" in text
    assert f"Next: ariadne ok {tid}" in text


# ---------- closed sets: flows, tools, models ----------

def test_a_task_naming_an_unapproved_flow_is_rejected(env):
    w = make_worker(env, FakeRunner())
    tid = w.store.submit("write something", "test", str(env), flow="writing")
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "rejected" and "not an approved flow" in t["result"]


def test_a_flow_folder_outside_the_approved_list_is_refused(tmp_path):
    d = tmp_path / "flows" / "rogue"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text("name: rogue\ndescription: d\nwhen: w\n")
    (tmp_path / "flows" / "flows.yaml").write_text("approved: [coding]\n")
    with pytest.raises(flowlib.FlowError, match="not an approved flow"):
        flowlib.load_flows(tmp_path / "flows")


def test_a_flow_using_an_unapproved_tool_is_refused(tmp_path):
    d = tmp_path / "flows" / "x"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text("name: x\ndescription: d\nwhen: w\nmcp_servers: [memory]\nrequires: [rust]\n")
    (tmp_path / "flows" / "mcp_servers.yaml").write_text("memory: {command: x, args: []}\n")
    (tmp_path / "flows" / "tools.yaml").write_text("approved: {mcp: [memory], system: [git]}\n")
    with pytest.raises(flowlib.FlowError, match="not approved"):
        flowlib.load_flows(tmp_path / "flows")


def test_an_unapproved_model_family_is_refused(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text("policy: {families: [gemma, qwen]}\n"
                 "models:\n  llama-3-8b: {kind: agent, roles: [coding], size_gb: 5}\n")
    with pytest.raises(modellib.ModelError, match="not approved"):
        modellib.load(p)


def test_the_flow_brief_and_shared_skills_reach_the_plan(env):
    run = FakeRunner()
    w = make_worker(env, run)
    w.store.submit("fix the bug", "test", str(env))
    w.run_once()
    prompt = run.calls[0][2]
    assert "HOW THIS FLOW WORKS" in prompt and "One agent model for the whole repository" in prompt
    assert "SHARED SKILLS" in prompt


def test_the_orchestrator_model_is_unloaded_before_execution(env):
    w = make_worker(env, FakeRunner())
    freed = []
    w.unload = lambda: (freed.append(1), True)[1]
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once()
    assert not freed                                     # still planning
    w.store.approve(tid)
    w.run_once()
    assert freed
    assert any("orchestrator model unloaded" in e for e in w.store.get(tid)["events"])


def test_session_defaults_to_the_repo_folder(tmp_path):
    assert orch._default_session(str(tmp_path / "proj")) == "proj"
    assert orch._default_session(str(tmp_path / "my repo")) == "my-repo"
