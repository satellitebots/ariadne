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


