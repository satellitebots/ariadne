"""The runtime frame: a scripted model drives the loop, the tools, the phase filter, budgets and resume.

No GPU, no HTTP except one stub that proves the client speaks OpenAI tools.
"""
import http.server
import json
import threading

import pytest

from ariadne import runtime
from ariadne.runtime import loop, model as model_mod, session as session_mod, tools as tools_mod


def tool_reply(name, arguments, call_id="c1", content=""):
    fn = {"name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments)}
    return {"choices": [{"message": {"role": "assistant", "content": content,
                                     "tool_calls": [{"id": call_id, "type": "function", "function": fn}]}}]}


def say(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


class Script:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, body):
        # the loop appends to its own list after the call: snapshot what was actually sent
        self.calls.append({**body, "messages": list(body.get("messages") or [])})
        return self.replies.pop(0)


@pytest.fixture
def ws(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    (d / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    return d


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def test_a_turn_calls_a_tool_and_answers(ws, home):
    run = Script(tool_reply("read_file", {"path": "calc.py"}), say("fixed it; tests pass"))
    events = []
    answer = runtime.run("fix add()", home=home, workspace=ws, phase="execute", model="m", session="t1",
                         transport=run, on_event=lambda k, d: events.append((k, d)))
    assert (answer.text, answer.turns, answer.stopped) == ("fixed it; tests pass", 2, "")
    assert "return a - b" in json.dumps(session_mod.load(home, "t1"), ensure_ascii=False)
    assert events == [("tool", 'read_file {"path": "calc.py"}')]
    assert run.calls[0]["tools"] and run.calls[0]["tool_choice"] == "auto"


def test_the_plan_phase_is_offered_only_read_only_tools(ws, home):
    run = Script(say("here is the plan"))
    runtime.run("plan it", home=home, workspace=ws, phase="plan", model="m", session="p1", transport=run)
    names = [t["function"]["name"] for t in run.calls[0]["tools"]]
    assert names == ["read_file", "search_files", "list_dir"]


def test_a_write_tool_cannot_be_smuggled_into_the_plan_phase(ws, home):
    run = Script(tool_reply("write_file", {"path": "new.txt", "content": "x"}), say("done"))
    runtime.run("plan", home=home, workspace=ws, phase="plan", model="m", session="p2", transport=run)
    assert not (ws / "new.txt").exists()
    tool_msg = [m for m in session_mod.load(home, "p2") if m.get("role") == "tool"][0]
    assert "not available in the plan phase" in tool_msg["content"]


def test_a_tool_failure_is_a_result_the_model_can_read(ws, home):
    run = Script(tool_reply("read_file", {"path": "missing.py"}), say("it is not there"))
    runtime.run("look", home=home, workspace=ws, phase="execute", model="m", session="e1", transport=run)
    msg = [m for m in session_mod.load(home, "e1") if m.get("role") == "tool"][0]
    assert msg["content"].startswith("ERROR: no such file")


def test_paths_outside_the_workspace_are_refused(ws, home):
    assert tools_mod.call("read_file", {"path": "../../etc/passwd"}, str(ws), "execute").startswith("ERROR: ")
    assert "outside the workspace" in tools_mod.call("read_file", {"path": "../x"}, str(ws), "execute")


def test_max_turns_stops_with_what_it_has(ws, home):
    run = Script(*[tool_reply("list_dir", {}, call_id=f"c{i}", content="working") for i in range(5)])
    answer = runtime.run("loop", home=home, workspace=ws, phase="execute", model="m", session="x1",
                         max_turns=2, transport=run)
    assert answer.turns == 2 and answer.stopped == "max_turns" and answer.text == "working"


def test_the_time_budget_stops_before_the_next_call(ws, home):
    ticks = iter([0, 0, 100, 200])
    run = Script(tool_reply("list_dir", {}), say("late"))
    answer = runtime.run("slow", home=home, workspace=ws, phase="execute", model="m", session="b1", budget=50,
                         transport=run, clock=lambda: next(ticks))
    assert answer.stopped == "budget" and len(run.calls) == 1


def test_a_session_resumes_the_same_conversation(ws, home):
    runtime.run("first", home=home, workspace=ws, phase="execute", model="m", session="s1", transport=Script(say("one")))
    second = Script(say("two"))
    runtime.run("second", home=home, workspace=ws, phase="execute", model="m", session="s1", transport=second)
    sent = [m["content"] for m in second.calls[0]["messages"] if m["role"] in ("user", "assistant")]
    assert sent == ["first", "one", "second"]                  # history, then the new turn
    assert second.calls[0]["messages"][0]["role"] == "system"


def test_invalid_tool_arguments_come_back_as_an_error(ws, home):
    run = Script(tool_reply("read_file", "{not json"), say("retry"))
    runtime.run("x", home=home, workspace=ws, phase="execute", model="m", session="a1", transport=run)
    msg = [m for m in session_mod.load(home, "a1") if m.get("role") == "tool"][0]
    assert "not valid JSON" in msg["content"]


def test_the_terminal_tool_runs_in_the_workspace(ws):
    out = tools_mod.call("terminal", {"command": "echo hi"}, str(ws), "execute")
    assert out.startswith("exit 0") and "hi" in out


def test_a_run_needs_a_model(home, ws):
    with pytest.raises(loop.RunError, match="explicitly chosen model"):
        runtime.run("x", home=home, workspace=ws, model="")


def test_the_client_speaks_openai_tools(monkeypatch, tmp_path):
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            seen["body"] = json.loads(self.rfile.read(n))
            payload = json.dumps(tool_reply("read_file", {"path": "a.py"}, call_id="call_9")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ARIADNE_LLM_URL", f"http://127.0.0.1:{httpd.server_port}/v1")
        out = model_mod.chat([{"role": "user", "content": "hi"}], model="qwen3.5-9b",
                             tools=tools_mod.offered("execute"))
    finally:
        httpd.shutdown()
    assert out["tool_calls"] == [{"id": "call_9", "name": "read_file", "arguments": {"path": "a.py"}}]
    assert seen["body"]["model"] == "qwen3.5-9b" and seen["body"]["tools"]
