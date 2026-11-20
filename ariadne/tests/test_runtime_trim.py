"""B12.6a: context trimming in the loop and the worker's per-run log artifact.

Trimming: before every model call a message list over the budget is cut to the system message plus a recent tail,
the system message says what was omitted, the trimmed list is what the session saves, and the order never breaks
(every kept tool result still follows the call it answers). The per-run log: one artifact under paths.LOGS with
the header, the prompt, one line per tool call, the report and the stop reason; a failed write leaves the run
intact. No network, no model: the model is scripted as in test_runtime.py, and the worker test stubs chat().
"""
from pathlib import Path

import pytest

from ariadne import paths, runtime
from ariadne.runtime import session as session_mod
from ariadne.tests.test_runtime import Script, say, tool_reply


@pytest.fixture
def ws(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    (d / "big.txt").write_text("\n".join(f"line {i}: " + "w" * 50 for i in range(11)), encoding="utf-8")
    (d / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    return d


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def ten_reads():
    return Script(*[tool_reply("read_file", {"path": "big.txt"}, call_id=f"c{i}") for i in range(1, 11)],
                  say("all ten reads are in; done"))


def test_a_long_run_trims_its_context(ws, home):
    answer = runtime.run("read the file ten times", home=home, workspace=ws, phase="execute", model="m",
                         session="t1", transport=ten_reads(), context_tokens=200, trim_at=0.5)
    assert (answer.text, answer.stopped) == ("all ten reads are in; done", "")
    assert answer.dropped > 0
    saved = session_mod.load(home, "t1")
    # the same run without trimming keeps every message
    runtime.run("read the file ten times", home=home, workspace=ws, phase="execute", model="m", session="n1",
                transport=ten_reads())
    assert len(saved) < len(session_mod.load(home, "n1"))
    assert saved[0]["role"] == "system"
    assert "Earlier turns omitted" in saved[0]["content"]
    # every kept tool result still answers a call in the kept list, in order
    open_calls = set()
    for m in saved:
        if m.get("role") == "assistant":
            open_calls.update(c["id"] for c in m.get("tool_calls") or [])
        elif m.get("role") == "tool":
            assert m["tool_call_id"] in open_calls, f"orphaned tool result {m['tool_call_id']}"
            open_calls.discard(m["tool_call_id"])


def test_a_small_session_under_the_budget_keeps_everything(ws, home):
    run = Script(tool_reply("list_dir", {}), say("small and done"))
    answer = runtime.run("look", home=home, workspace=ws, phase="execute", model="m", session="s1", transport=run)
    assert answer.dropped == 0
    saved = session_mod.load(home, "s1")
    assert [m["role"] for m in saved] == ["system", "user", "assistant", "tool", "assistant"]
    assert "Earlier turns omitted" not in saved[0]["content"]


def test_the_last_user_prompt_is_still_the_last_user_message_after_trimming(ws, home):
    first = Script(*[tool_reply("read_file", {"path": "calc.py"}, call_id=f"c{i}") for i in range(1, 6)],
                   say("first batch read"))
    runtime.run("first batch", home=home, workspace=ws, phase="execute", model="m", session="r1", transport=first)
    second = Script(*[tool_reply("read_file", {"path": "calc.py"}, call_id=f"c{i}") for i in range(6, 8)],
                    say("second batch read"))
    answer = runtime.run("second batch", home=home, workspace=ws, phase="execute", model="m", session="r1",
                         transport=second, context_tokens=600, trim_at=0.5)
    assert (answer.text, answer.stopped) == ("second batch read", "")
    assert answer.dropped > 0
    users = [m for m in session_mod.load(home, "r1") if m.get("role") == "user"]
    assert users and users[-1]["content"] == "second batch"
    # ... and the trimmed history is still well-ordered end to end
    open_calls = set()
    for m in session_mod.load(home, "r1"):
        if m.get("role") == "assistant":
            open_calls.update(c["id"] for c in m.get("tool_calls") or [])
        elif m.get("role") == "tool":
            assert m["tool_call_id"] in open_calls
            open_calls.discard(m["tool_call_id"])


def test_runtime_run_writes_a_per_run_log(tmp_path, monkeypatch):
    from ariadne import flows as flowlib
    from ariadne import worker as workerlib
    from ariadne.runtime import model as model_mod

    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")      # the session lands in tmp, not the state dir
    monkeypatch.setattr(model_mod, "chat", lambda messages, **kw:
                        {"content": "reported", "tool_calls": [],
                         "raw": {"role": "assistant", "content": "reported"}})
    fl = flowlib.Flow(name="logtest", description="d", when="w", mcp_servers=[])
    r = workerlib.runtime_run(fl, "execute", "do the thing", str(tmp_path), "t9")
    assert r.exit_code == 0
    assert r.log
    log = Path(r.log)
    assert log.parent == tmp_path / "logs" and log.exists()
    text = log.read_text(encoding="utf-8")
    assert "do the thing" in text and "reported" in text and "phase: execute" in text
    assert "flow: logtest" in text and "workspace:" in text
