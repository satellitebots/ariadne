"""B12.6b: the own runtime's todo tool, the park step boundary and the MCP marker files.

The model is scripted as in test_runtime.py - no network, no GPU. `runtime_run` gets a monkeypatched
`runtime.model.chat`: one plain reply per test case, and - where the run must reach a step boundary before it
answers - a tool call first, because the loop asks the checkpoint only at the top of a turn after the first one.
"""
import json
from pathlib import Path

import pytest

from ariadne import paths, runtime
from ariadne.runtime import session as session_mod, tools as tools_mod
from ariadne.tests.test_runtime import Script, say, tool_reply


@pytest.fixture
def ws(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    (d / "a.txt").write_text("one\n", encoding="utf-8")
    return d


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def test_todo_write_writes_the_checklist(ws):
    out = tools_mod.call("todo_write", {"items": ["read the plan", "fix add()", "run the tests"],
                                        "note": "left open by the previous run"}, str(ws), "execute")
    assert out == "wrote 3 item(s) to .ariadne/todo.md"
    text = (ws / ".ariadne" / "todo.md").read_text(encoding="utf-8")
    assert "> left open by the previous run" in text
    assert text.count("- [ ]") == 3
    assert "- [ ] fix add()" in text


def test_todo_write_is_refused_in_the_plan_phase_and_writes_nothing(ws):
    out = tools_mod.call("todo_write", {"items": ["x"], "note": "n"}, str(ws), "plan")
    assert out.startswith("ERROR: ") and "read-only" in out
    assert not (ws / ".ariadne" / "todo.md").exists()


def test_the_loop_parks_at_the_step_boundary(ws, home):
    # turn 1: the model calls a tool and the result is saved; the park request is seen at the top of turn 2
    run = Script(tool_reply("list_dir", {}), say("done"))
    answer = runtime.run("go", home=home, workspace=ws, phase="execute", model="m", session="pk1",
                         transport=run, checkpoint=lambda: True)
    assert answer.stopped == "parked" and answer.turns == 1
    assert session_mod.path(home, "pk1").exists()
    tool_msg = [m for m in session_mod.load(home, "pk1") if m.get("role") == "tool"]
    assert tool_msg and tool_msg[0]["name"] == "list_dir" and "a.txt" in tool_msg[0]["content"]
    assert len(run.calls) == 1                                  # the second model call never happened


def test_the_loop_answers_normally_without_a_park(ws, home):
    run = Script(tool_reply("list_dir", {}), say("done"))
    answer = runtime.run("go", home=home, workspace=ws, phase="execute", model="m", session="pk2",
                         transport=run, checkpoint=lambda: None)
    assert (answer.stopped, answer.text, answer.turns) == ("", "done", 2)


def test_the_checkpoint_is_not_asked_on_the_first_turn(ws, home):
    asked = []
    run = Script(say("first answer"))
    answer = runtime.run("go", home=home, workspace=ws, phase="execute", model="m", session="pk3",
                         transport=run, checkpoint=lambda: (asked.append(1), True)[1])
    assert (answer.stopped, answer.text) == ("", "first answer") and asked == []


def parsed_tool(name, arguments, call_id="c1"):
    raw = {"role": "assistant", "content": "",
           "tool_calls": [{"id": call_id, "type": "function",
                           "function": {"name": name, "arguments": json.dumps(arguments)}}]}
    return {"content": "", "tool_calls": [{"id": call_id, "name": name, "arguments": arguments}], "raw": raw}


def parsed_say(text):
    raw = {"role": "assistant", "content": text}
    return {"content": text, "tool_calls": [], "raw": raw}


def test_runtime_run_parks_maps_125_and_writes_the_markers(tmp_path, monkeypatch):
    from ariadne import flows as flowlib, park as parklib, worker as workerlib
    from ariadne.runtime import model as model_mod

    ws = str(tmp_path / "ws")
    Path(ws).mkdir()
    monkeypatch.setattr(parklib, "requested", lambda: {"by": "test"})
    # a tool call first (the step boundary the park stops at), then the plain reply the run would have made
    replies = [parsed_tool("list_dir", {}), parsed_say("reported")]
    monkeypatch.setattr(model_mod, "chat", lambda messages, **kw: replies.pop(0))
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")    # flow.home lands in tmp, not the state dir
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")

    fl = flowlib.Flow(name="parktest", description="d", when="w", mcp_servers=[])
    r = workerlib.runtime_run(fl, "execute", "do it", ws, "t-park")
    assert r.exit_code == 125 == workerlib.PARKED
    assert "parked" in r.text and "reported" not in r.text
    assert (fl.home / "ariadne_task").read_text(encoding="utf-8") == "t-park"
    assert (fl.home / "ariadne_workspace").read_text(encoding="utf-8") == ws
    assert (fl.home / "ariadne_phase").read_text(encoding="utf-8") == "execute"


def test_runtime_run_without_a_park_answers_0(tmp_path, monkeypatch):
    from ariadne import flows as flowlib, park as parklib, worker as workerlib
    from ariadne.runtime import model as model_mod

    ws = str(tmp_path / "ws")
    Path(ws).mkdir()
    monkeypatch.setattr(parklib, "requested", lambda: None)
    replies = [parsed_tool("list_dir", {}), parsed_say("reported")]
    monkeypatch.setattr(model_mod, "chat", lambda messages, **kw: replies.pop(0))
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")

    fl = flowlib.Flow(name="parktest", description="d", when="w", mcp_servers=[])
    r = workerlib.runtime_run(fl, "execute", "do it", ws, "t-ok")
    assert r.exit_code == 0 and "reported" in r.text
    assert (fl.home / "ariadne_task").read_text(encoding="utf-8") == "t-ok"
    assert (fl.home / "ariadne_workspace").read_text(encoding="utf-8") == ws


def test_runtime_run_side_phase_writes_the_plan_marker_and_never_parks(tmp_path, monkeypatch):
    from ariadne import flows as flowlib, park as parklib, worker as workerlib
    from ariadne.runtime import model as model_mod

    ws = str(tmp_path / "ws")
    Path(ws).mkdir()
    # a park request is live, but a side run passes checkpoint=None: it answers normally
    monkeypatch.setattr(parklib, "requested", lambda: {"by": "test"})
    monkeypatch.setattr(model_mod, "chat", lambda messages, **kw: parsed_say("the handoff brief"))
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")

    fl = flowlib.Flow(name="parktest", description="d", when="w", mcp_servers=[])
    r = workerlib.runtime_run(fl, "checkpoint:plan", "write the handoff", ws, "t-side")
    assert r.exit_code == 0 and "handoff" in r.text
    assert (fl.home / "ariadne_phase").read_text(encoding="utf-8") == "plan"
    assert (fl.home / "ariadne_task").read_text(encoding="utf-8") == "t-side"
    assert (fl.home / "ariadne_workspace").read_text(encoding="utf-8") == ws
