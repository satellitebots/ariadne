"""Unit tests for Ariadne's orchestrator, flows and shared memory (no models, no Hermes)."""
import json
from pathlib import Path

import pytest

from ariadne import flows as flowlib
from ariadne import models as modellib
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
    cfg = flowlib.mcp_server_config(fl["coding"], REPO_FLOWS)
    assert "ariadne.memory_mcp" in " ".join(cfg["memory"]["args"])
    assert "ariadne.git_mcp" in " ".join(cfg["git"]["args"])
    assert "fix-and-verify" in fl["coding"].skills and "planning-lessons" in flowlib.shared_skill_dirs("coding")
    assert "git_status" in fl["coding"].plan_tools


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


def test_activity_log_records_task_events_mcp_calls_and_worker_lines(env, monkeypatch):
    from ariadne import activity
    monkeypatch.setattr(activity, "LOG_DIR", env)
    from ariadne import durable
    st = durable.Store(env / "a.db")
    tid = "r1"
    st.event(tid, "brief", "from test: x")

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
    assert f"[{tid}] brief: from test: x" in text
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


