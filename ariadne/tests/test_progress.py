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


def test_a_worker_repeating_itself_is_reported_as_looping_once(tmp_path):
    got = []
    p = engine.Progress(tmp_path, "C:/ws", lambda k, d: got.append((k, d)))
    cycle = ["read a", "read b", "read c"]
    for what in cycle * 4:                             # 4 rounds: not yet a loop
        p._watch_for_loops(what)
    assert not got
    for what in cycle * 3:
        p._watch_for_loops(what)
    loops = [d for k, d in got if k == "looping"]
    assert len(loops) == 1 and "3 tool call(s)" in loops[0] and "not stopped" in loops[0]
    p._watch_for_loops("wrote REPORT.md")              # real work: the loop is over, a new one may be reported
    for what in ["ran: x"] * 5:
        p._watch_for_loops(what)
    assert len([k for k, _ in got if k == "looping"]) == 2


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


def test_a_steering_note_holds_for_every_later_step(tmp_path):
    store = durable.Store(tmp_path / "a.db")
    broker = Broker(tmp_path / "m.db", server=FakeServer(), poll=0.01)
    rid = start(store, make_spec(tmp_path / "ws", [{"title": "A", "instruction": "a", "outputs": []},
                                                    {"title": "B", "instruction": "b", "outputs": []},
                                                    {"title": "C", "instruction": "c", "outputs": []}]))

    def first(ws, prompt):        # a note given while step 1 runs is meant for step 3
        store.steer(rid, "in step 3 use news from the last 2 weeks only")
        return "ok", 0
    script = Script({1: [first]})
    engine.Engine(store, FLOWS, broker, step_runner=script).run_once()
    prompts = {n: p for kind, n, p, *_ in script.calls if kind == "step"}
    assert "last 2 weeks" in prompts[2] and "last 2 weeks" in prompts[3]


def test_terminal_chat_commands_act_without_the_model(tmp_path, monkeypatch):
    from ariadne import __main__ as cli, park
    monkeypatch.setattr(park, "FLAG", tmp_path / "park.json")
    store = durable.Store(tmp_path / "a.db")
    broker = Broker(tmp_path / "m.db", server=FakeServer(), poll=0.01)
    rid = start(store, make_spec(tmp_path / "ws", [{"title": "A", "instruction": "a", "outputs": []}]))
    store.run_set(rid, status="running", step=1)
    store.event(rid, "tool", "step 1: wrote NOTES.md")
    monkeypatch.setattr(verbs, "ctx", verbs.Ctx(store=store, broker=broker, flows=FLOWS))
    assert "wrote NOTES.md" in cli.chat_command("/status")
    assert "parking" in cli.chat_command("/park") and park.requested()
    assert "noted" in cli.chat_command("/steer use primary sources")
    assert store.steers(rid) == ["use primary sources"]
    assert "unknown command" in cli.chat_command("/nope")


def test_an_unchanged_model_server_config_is_never_rewritten(tmp_path, monkeypatch):
    # llama-swap -watch-config reloads on every write and fails requests in flight; the idle daemon wrote every 2 s
    from ariadne import serve
    monkeypatch.setattr(serve, "CONFIG", tmp_path / "llama-swap.yaml")
    monkeypatch.setattr(serve, "_render_text", lambda: "models: {}\n")
    serve.render_config()
    first = serve.CONFIG.stat().st_mtime_ns
    import time as _t
    _t.sleep(0.05)
    assert serve.apply_if_changed() is False
    serve.render_config()
    assert serve.CONFIG.stat().st_mtime_ns == first
    monkeypatch.setattr(serve, "_render_text", lambda: "models: {a: 1}\n")
    assert serve.apply_if_changed() is True


def test_the_orchestrator_loop_has_no_cap_or_clock_by_default():
    from ariadne import orchestrate
    o = orchestrate.Orchestrator()
    assert (o.max_turns, o.budget) == (0, 0)
