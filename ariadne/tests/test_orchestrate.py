import json

import pytest

from ariadne import durable, flows as flowlib, orchestrate, park, spec as speclib, verbs
from ariadne.broker import Broker
from ariadne.tests.test_broker import FakeServer
from ariadne.tests.test_durable import FakeCatalog

FLOWS = flowlib.load_flows()


def model_says(*replies):
    """A scripted model: each reply is text, or (tool name, arguments) for one tool call."""
    queue, seen = list(replies), []

    def transport(url, body):
        seen.append(body)
        r = queue.pop(0)
        if isinstance(r, tuple):
            fn = {"name": r[0], "arguments": json.dumps(r[1])}
            msg = {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{len(seen)}", "type": "function",
                                                                        "function": fn}]}
        else:
            msg = {"role": "assistant", "content": r}
        return {"choices": [{"message": msg}]}
    return transport, seen


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    c = verbs.Ctx(store=durable.Store(tmp_path / "a.db"), flows=FLOWS, catalog=FakeCatalog(),
                  broker=Broker(tmp_path / "m.db", server=FakeServer(), poll=0.01))
    monkeypatch.setattr(verbs, "ctx", c)
    monkeypatch.setattr(park, "FLAG", tmp_path / "park.json")
    return c


def test_the_orchestrator_fills_a_draft_and_cannot_work(ctx, tmp_path):
    d = verbs.call("draft", text="Is GOOGL trending up?", flow="investigation")
    sp = dict(d["spec"], name="googl-daily", workspace=str(tmp_path / "ws"),
              params={"question": "Is GOOGL trending up?", "must_contain": "a verdict", "within_days": "30"})
    transport, seen = model_says(("draft_update", {"yaml": speclib.dump(sp)}),
                                 "It runs four steps on GOOGL. Sign it when it looks right.")
    ctx.orchestrator = orchestrate.Orchestrator(transport=transport, model="qwen")
    out = verbs.call("say", draft=d["id"], message="weekdays at 7 is fine later; for now manual")
    assert out["ready"] and "Sign it" in out["reply"]
    tools = {t["function"]["name"] for t in seen[0]["tools"]}
    assert "draft_update" in tools and "web_search" in tools and "read_file" in tools
    assert not tools & {"write_file", "patch", "terminal", "say", "chat", "define", "events"}
    draft_tool = next(t for t in seen[0]["tools"] if t["function"]["name"] == "draft_update")
    assert "draft" not in draft_tool["function"]["parameters"]["properties"]   # bound to this draft
    assert any("CURRENT DRAFT" in (m.get("content") or "") for m in seen[0]["messages"] if m["role"] == "user")
    assert ctx.broker.holder() is None                                         # the turn gave the machine back


def test_chat_can_drive_runs_through_the_same_verbs(ctx, tmp_path):
    d = verbs.call("define", yaml=speclib.dump(dict(speclib.from_template(FLOWS["investigation"])[0],
                                                    name="googl-daily", workspace=str(tmp_path / "ws"),
                                                    params={"question": "q", "must_contain": "m", "within_days": "30"})))
    verbs.call("sign", draft=d["id"])
    transport, seen = model_says(("run", {"task": "googl-daily"}), "Started; it is queued for the machine.")
    ctx.orchestrator = orchestrate.Orchestrator(transport=transport, model="qwen")
    out = verbs.call("chat", message="run googl-daily now")
    assert "queued" in out["reply"] and len(ctx.store.runs()) == 1
    assert [m["role"] for m in out["messages"]] == ["person", "orchestrator"]


def test_every_front_offers_the_same_verbs():
    """The contract: chat gets every verb except the conversation verbs and the MCP-only bypass."""
    offered = {t["function"]["name"] for t in orchestrate.VerbTools().offered()}
    expected = {n for n, v in verbs.VERBS.items() if not v.mcp_only} - set(orchestrate.CONVERSATION_VERBS)
    assert offered == expected
