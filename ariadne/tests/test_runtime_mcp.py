"""B12.3: the flow's MCP servers attached to the own runtime as `mcp__` tools.

The data server is the real one (python -m ariadne.data_mcp over stdio, spawned per Pool); only the model is scripted,
as in test_runtime.py. No network, no GPU: a Pool is a subprocess the test owns and closes.
"""
import time

import pytest

from ariadne import paths, runtime
from ariadne.runtime import mcp as mcp_mod
from ariadne.runtime import session as session_mod
from ariadne.tests.test_runtime import Script, say, tool_reply


def data_cfg():
    return {"data": {"command": str(paths.VENV_PY), "args": ["-m", "ariadne.data_mcp"],
                     "env": {"PYTHONPATH": str(paths.ROOT)}}}


@pytest.fixture
def csv(tmp_path):
    p = tmp_path / "people.csv"
    p.write_text("name,score\nada,95\nbob,70\ncid,88\n", encoding="utf-8")
    return p


def test_a_pool_attaches_the_server_and_answers(csv):
    pool = mcp_mod.Pool(data_cfg())
    try:
        assert pool.connected == {"data"} and pool.errors == []
        names = [s["function"]["name"] for s in pool.schemas]
        assert "mcp__data__profile" in names
        out = pool.call("mcp__data__profile", {"source": str(csv)})
        assert not out.startswith("ERROR: ") and "name" in out and "score" in out
    finally:
        pool.close()


def test_the_plan_phase_sees_only_the_plan_tools_and_the_rest_is_refused(csv):
    pool = mcp_mod.Pool(data_cfg(), plan_allowed={"profile"})
    try:
        assert [s["function"]["name"] for s in pool.offered(True)] == ["mcp__data__profile"]
        assert len([s["function"]["name"] for s in pool.offered()]) == 4   # execute sees everything
        out = pool.call("mcp__data__query", {"source": str(csv), "sql": "select 1"}, read_only=True)
        assert out.startswith("ERROR: ") and "plan phase" in out
    finally:
        pool.close()


def test_the_loop_dispatches_mcp_calls_to_the_pool(csv, tmp_path):
    home = tmp_path / "home"
    pool = mcp_mod.Pool(data_cfg())
    try:
        run = Script(tool_reply("mcp__data__profile", {"source": str(csv)}), say("the columns are name and score"))
        answer = runtime.run("profile it", home=home, workspace=csv.parent, phase="execute", model="m",
                             session="m1", transport=run, mcp=pool)
        assert (answer.text, answer.stopped) == ("the columns are name and score", "")
        tool_msg = [m for m in session_mod.load(home, "m1") if m.get("role") == "tool"][0]
        assert tool_msg["name"] == "mcp__data__profile" and "score" in tool_msg["content"]
        # same pool in a read-only phase: the call is refused, nothing is written
        out = csv.parent / "out.csv"
        run2 = Script(tool_reply("mcp__data__transform",
                                 {"source": str(csv), "sql": "select 1", "output": str(out)}), say("done"))
        runtime.run("x", home=home, workspace=csv.parent, phase="plan", model="m", session="m2", transport=run2,
                    mcp=pool)
        tool_msg = [m for m in session_mod.load(home, "m2") if m.get("role") == "tool"][0]
        assert tool_msg["content"].startswith("ERROR: ") and "plan phase" in tool_msg["content"]
        assert not out.exists()
    finally:
        pool.close()


def test_a_server_that_will_not_start_is_an_error_and_close_does_not_hang():
    pool = mcp_mod.Pool({"nope": {"command": "definitely-not-a-command", "args": []}})
    assert pool.connected == set() and len(pool.errors) == 1 and "nope" in pool.errors[0]
    assert pool.call("mcp__nope__any", {}).startswith("ERROR: ")
    t0 = time.time()
    pool.close(wait=5)
    assert time.time() - t0 < 5


