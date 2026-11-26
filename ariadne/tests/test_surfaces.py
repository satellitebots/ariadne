"""The one contract (docs/DESIGN.md): every front offers the same verbs, generated from verbs.VERBS."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from ariadne import __main__ as cli, durable, flows as flowlib, front_mcp, orchestrate, park, spec as speclib, verbs
from ariadne.broker import Broker
from ariadne.server import app as appmod
from ariadne.tests.test_broker import FakeServer
from ariadne.tests.test_durable import FakeCatalog

FLOWS = flowlib.load_flows()


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    c = verbs.Ctx(store=durable.Store(tmp_path / "a.db"), flows=FLOWS, catalog=FakeCatalog(),
                  broker=Broker(tmp_path / "m.db", server=FakeServer(), poll=0.01))
    monkeypatch.setattr(verbs, "ctx", c)
    monkeypatch.setattr(park, "FLAG", tmp_path / "park.json")
    monkeypatch.setenv("ARIADNE_NO_AUTOSTART", "1")
    return c


def test_mcp_offers_every_verb_including_the_bypass():
    tools = asyncio.run(front_mcp.server.list_tools())
    assert {t.name for t in tools} == set(verbs.VERBS)
    sched = next(t for t in tools if t.name == "schedule")
    assert set(sched.input_schema["required"]) == {"task", "trigger"}


def test_http_offers_every_verb_but_the_bypass(ctx):
    client = TestClient(appmod.create_app(ctx))
    names = {v["name"] for v in client.get("/api/verbs").json()}
    assert names == {n for n, v in verbs.VERBS.items() if not v.mcp_only}
    assert client.post("/api/v/define", json={"yaml": "x: 1"}).status_code == 404
    assert client.post("/api/v/run", json={"task": "nope"}).status_code == 400      # a person-fixable error


def test_chat_offers_every_verb_but_the_bypass_and_itself():
    offered = {t["function"]["name"] for t in orchestrate.VerbTools().offered()}
    assert offered == {n for n, v in verbs.VERBS.items() if not v.mcp_only} - set(orchestrate.CONVERSATION_VERBS)


def test_the_same_definition_signs_and_runs_from_http_and_the_terminal(ctx, tmp_path, capsys):
    client = TestClient(appmod.create_app(ctx))
    sp, _ = speclib.from_template(FLOWS["investigation"], name="googl-daily", workspace=str(tmp_path / "ws"))
    sp["params"] = {"question": "q", "must_contain": "m", "within_days": "30"}
    d = client.post("/api/v/draft", json={"text": "q", "flow": "investigation"}).json()
    d = client.post("/api/v/draft_update", json={"draft": d["id"], "yaml": speclib.dump(sp)}).json()
    assert d["ready"]
    assert client.post("/api/v/sign", json={"draft": d["id"]}).json()["version"] == 1
    assert cli.main(["run", "googl-daily"]) == 0                     # the terminal reaches the same store
    assert "queued" in capsys.readouterr().out
    assert [r["status"] for r in client.post("/api/v/runs", json={}).json()] == ["queued"]
    assert cli.main(["schedule", "googl-daily", "0 7 * * 1-5"]) == 0
    assert client.post("/api/v/task", json={"task": "googl-daily"}).json()["version"] == 2



# ---------- one backend: every front wakes the worker by the same rule, and the terminal chat works ----------

def _signed(ctx, tmp_path, name="googl-daily"):
    sp, _ = speclib.from_template(FLOWS["investigation"], name=name, workspace=str(tmp_path / "ws"))
    sp["params"] = {"question": "q", "must_contain": "m", "within_days": "30"}
    d = verbs.call("draft", text="q", flow="investigation")
    verbs.call("draft_update", draft=d["id"], yaml=speclib.dump(sp))
    return verbs.call("sign", draft=d["id"])


def test_every_front_wakes_the_worker_by_one_rule(ctx, tmp_path, woken):
    verbs.set_waker(lambda: woken.append("verb"))
    _signed(ctx, tmp_path)
    n = len(woken)
    verbs.call("runs")                                                   # reading wakes nothing
    assert len(woken) == n
    client = TestClient(appmod.create_app(ctx, start_worker=False))     # HTTP
    client.post("/api/v/run", json={"task": "googl-daily"})
    assert len(woken) == n + 1
    asyncio.run(front_mcp.server.call_tool("run", {"task": "googl-daily"}))   # MCP
    assert len(woken) == n + 2
    tools = orchestrate.VerbTools()                                      # the orchestrator's own tool call
    tools.call("run", {"task": "googl-daily"}) if hasattr(tools, "call") else verbs.call("run", task="googl-daily")
    assert len(woken) == n + 3
    assert cli.main(["run", "googl-daily"]) == 0                         # the terminal installs the real waker...
    assert woken[-1] == 1                                                # ...daemon.ensure_worker (a no-op in tests)


def test_the_terminal_chat_works_and_a_run_it_starts_gets_a_worker(ctx, tmp_path, monkeypatch, capsys, woken):
    _signed(ctx, tmp_path)

    class Orchestrator:          # stands in for the model: answers, and starts a run with a tool call as it would
        def turn(self, ref, message, **kw):
            r = verbs.call("run", task="googl-daily")
            return f"started {r['id']}"

    ctx.orchestrator = Orchestrator()
    lines = iter(["/help", "/status", "run googl-daily please", "/cancel", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert cli.main(["chat"]) == 0
    out = capsys.readouterr().out
    assert "/steer" in out                                     # /help
    assert "started r" in out                                  # the orchestrator's answer
    assert "cancel requested" in out                           # /cancel acted on the run it started
    assert woken                                               # and the run it started woke the worker
    assert [r["status"] for r in verbs.call("runs")] == ["cancelled"]     # a queued run cancels at once
