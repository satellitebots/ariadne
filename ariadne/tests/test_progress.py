"""Nothing stops a run on its own; what a worker does is pushed out as it happens so anyone can see it moving."""
import json

from ariadne import durable, engine, verbs
from ariadne.broker import Broker
from ariadne.tests.test_broker import FakeServer
from ariadne.tests.test_engine import FLOWS, Script, make_spec, start


def test_tool_calls_read_as_what_changed_or_ran():
    ws = "C:/repos/x"
    assert engine.describe_tool("write_file", {"path": "C:/repos/x/data/a.json", "content": "..."}, ws) == "wrote data/a.json"
    assert engine.describe_tool("patch", {"path": "C:\\repos\\x\\REPORT.md"}, ws) == "edited REPORT.md"
    assert engine.describe_tool("terminal", {"command": "ls -la"}, ws) == "ran: ls -la"
    assert engine.describe_tool("mcp__jobs__submit_job", {"command": "python s.py"}, ws) == "submitted a job: python s.py"
    assert engine.describe_tool("web_search", {"query": "GOOGL news"}, ws) == "searched the web: GOOGL news"


def test_progress_pushes_tool_and_model_calls_and_never_stops_anything(tmp_path):
    home, got, now = tmp_path, [], [1000.0]
    (home / "logs").mkdir()
    tools, agent = home / "logs" / "ariadne_tools.jsonl", home / "logs" / "agent.log"
    tools.write_text(json.dumps({"tool": "read_file", "args": {"path": "old"}}) + "\n", encoding="utf-8")
    p = engine.Progress(home, "C:/ws", lambda k, d: got.append((k, d)), clock=lambda: now[0])
    p.poll()
    assert got == []                                       # only what happens after it starts
    with open(tools, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": "write_file", "args": {"path": "C:/ws/REPORT.md"}}) + "\n")
        f.write('{"tool": "terminal", "args": {"comm')     # half a line: kept for the next poll
    agent.write_text("x INFO agent.conversation_loop: API call #3: model=m provider=custom in=16339 out=237 "
                     "total=16576 latency=20.7s id=y\n", encoding="utf-8")
    p.poll()
    assert got == [("tool", "wrote REPORT.md"), ("model", "model call 3: 16,339 tokens in, 237 out, 21 s")]
    with open(tools, "a", encoding="utf-8") as f:
        f.write('and": "pytest"}}\n')
    p.poll()
    assert got[-1] == ("tool", "ran: pytest")
    now[0] += engine.Progress.QUIET_S + 1
    p.poll()
    p.poll()
    assert [k for k, _ in got].count("quiet") == 1 and "nothing stops it" in got[-1][1]


def test_the_engine_records_progress_and_the_progress_verb_reads_it(tmp_path, monkeypatch):
    store = durable.Store(tmp_path / "a.db")
    broker = Broker(tmp_path / "m.db", server=FakeServer(), poll=0.01)
    rid = start(store, make_spec(tmp_path / "ws", [{"title": "A", "instruction": "a", "outputs": ["a.txt"]}]))

    class Pushing(Script):
        def __call__(self, flow, kind, prompt, ws, ref, model, tools, session=None, on_progress=None, **kw):
            assert "budget" not in kw and "turns" not in kw      # no clock, no cap is handed to a worker
            if kind == "step" and on_progress:
                on_progress("tool", f"wrote {ws}/a.txt".replace(ws + "/", ""))
                on_progress("model", "model call 1: 100 tokens in, 5 out, 2 s")
            return super().__call__(flow, kind, prompt, ws, ref, model, tools, session=session)
    e = engine.Engine(store, FLOWS, broker, step_runner=Pushing({1: [lambda ws, p: ((ws / "a.txt").write_text("x"), ("ok", 0))[1]]}))
    e.run_once()
    assert store.run(rid)["status"] == "done"
    monkeypatch.setattr(verbs, "ctx", verbs.Ctx(store=store, broker=broker, flows=FLOWS))
    p = verbs.call("progress", run=rid)
    assert p["tool_calls"] == 1 and p["model_calls"] == 1 and p["files_changed"] == ["a.txt"]
    assert p["last_activity"].startswith("step 1: model call 1") and p["seconds_since_activity"] is not None
    assert verbs.call("run_show", run=rid)["activity"]["kind"] == "model"


def test_the_newest_events_are_the_ones_shown(tmp_path):
    store = durable.Store(tmp_path / "a.db")
    for i in range(30):
        store.event("r1", "tool", f"call {i}")
    assert [e["detail"] for e in store.events("r1", limit=3, newest=True)] == ["call 27", "call 28", "call 29"]


def test_the_orchestrator_loop_has_no_cap_or_clock_by_default():
    from ariadne import orchestrate
    o = orchestrate.Orchestrator()
    assert (o.max_turns, o.budget) == (0, 0)
