import time
from datetime import datetime

import pytest

from ariadne import durable, flows as flowlib, park, spec as speclib, verbs
from ariadne.tests.test_broker import FakeServer
from ariadne.broker import Broker

FLOWS = flowlib.load_flows()


class FakeCatalog:
    def get(self, name):
        if name == "nope":
            raise KeyError(name)
        return name


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    c = verbs.Ctx(store=durable.Store(tmp_path / "a.db"), flows=FLOWS, catalog=FakeCatalog(),
                  broker=Broker(tmp_path / "m.db", server=FakeServer(), poll=0.01))
    monkeypatch.setattr(verbs, "ctx", c)
    monkeypatch.setattr(park, "FLAG", tmp_path / "park.json")
    return c


def good_spec(tmp_path, **over):
    sp, _ = speclib.from_template(FLOWS["investigation"], name="googl-daily", workspace=str(tmp_path / "ws"))
    sp["params"] = {"question": "Is GOOGL trending up?", "must_contain": "a verdict", "within_days": "30"}
    sp.update(over)
    return sp


def test_a_template_needs_its_params_and_a_name(tmp_path):
    sp, asks = speclib.from_template(FLOWS["investigation"])
    assert set(asks) == {"question", "must_contain", "within_days"} and len(sp["steps"]) == 5
    with pytest.raises(speclib.SpecError) as e:
        speclib.validate(sp, FLOWS)
    text = str(e.value)
    assert "name:" in text and "workspace:" in text and "question" in text   # all problems, not the first
    assert speclib.validate(good_spec(tmp_path), FLOWS)["steps"][1]["gate"]["type"] == "run"


def test_a_spec_refuses_the_repo_as_workspace_and_tools_outside_the_flow(tmp_path):
    from ariadne import paths
    bad = good_spec(tmp_path, workspace=str(paths.ROOT))
    bad["steps"][0]["tools"] = ["file", "ci"]
    with pytest.raises(speclib.SpecError) as e:
        speclib.validate(bad, FLOWS)
    assert "Ariadne's own repository" in str(e.value) and "tools ci" in str(e.value)
    ok = good_spec(tmp_path, workspace=str(paths.ROOT / "sandbox" / "googl"))
    speclib.validate(ok, FLOWS)


def test_triggers_and_next_due():
    sp = {"trigger": {"kind": "cron", "cron": "0 7 * * 1-5"}, "tz": "America/New_York"}
    after = datetime(2026, 11, 27, 12, 0).timestamp()           # a Friday afternoon (local clock of the test box)
    due = datetime.fromtimestamp(speclib.next_due(sp, after))
    assert due.weekday() == 0                                    # next is Monday
    assert speclib.next_due({"trigger": {"kind": "manual"}}, after) is None
    past = {"trigger": {"kind": "at", "at": "2020-01-01T07:00"}, "tz": "UTC"}
    assert speclib.next_due(past, time.time()) is None


def test_draft_sign_run_and_versions(ctx, tmp_path):
    d = verbs.call("draft", text="Is GOOGL trending up?", flow="investigation")
    assert not d["ready"] and d["messages"][0]["text"] == "Is GOOGL trending up?"
    with pytest.raises(verbs.VerbError, match="not ready to sign"):
        verbs.call("sign", draft=d["id"])
    d = verbs.call("draft_update", draft=d["id"], yaml=speclib.dump(good_spec(tmp_path)))
    assert d["ready"], d["problems"]
    t = verbs.call("sign", draft=d["id"])
    assert t["version"] == 1 and t["trigger"] == "runs when you start it"
    assert (ctx.store.specs_dir / t["id"] / "v1.yaml").exists()
    r = verbs.call("run", task="googl-daily")
    assert r["status"] == "queued" and r["steps_total"] == 5
    e = verbs.call("edit", task="googl-daily")
    sp = e["spec"]
    sp["goal"] = "changed"
    verbs.call("draft_update", draft=e["id"], yaml=speclib.dump(sp))
    t2 = verbs.call("sign", draft=e["id"])
    assert t2["version"] == 2 and ctx.store.run(r["id"])["version"] == 1   # a queued run keeps its version


def test_schedule_signs_a_new_version_and_the_store_says_what_is_due(ctx, tmp_path):
    d = verbs.call("define", yaml=speclib.dump(good_spec(tmp_path)))     # the MCP bypass: a full definition
    verbs.call("sign", draft=d["id"])
    t = verbs.call("schedule", task="googl-daily", trigger="0 7 * * 1-5")
    assert t["version"] == 2 and t["trigger"].startswith("weekdays at 07:00") and t["next_due"]
    assert ctx.store.due(t["next_due"] + 1)[0]["name"] == "googl-daily"
    verbs.call("unschedule", task="googl-daily")
    assert ctx.store.due(t["next_due"] + 1) == []


def test_run_controls_and_unknown_arguments(ctx, tmp_path):
    d = verbs.call("define", yaml=speclib.dump(good_spec(tmp_path)))
    verbs.call("sign", draft=d["id"])
    r = verbs.call("run", task="googl-daily")
    with pytest.raises(verbs.VerbError, match="only a running run"):
        verbs.call("park_run", run=r["id"])
    verbs.call("steer", run=r["id"], text="use weekly bars")
    assert ctx.store.take_steers(r["id"]) == ["use weekly bars"]
    assert verbs.call("cancel", run=r["id"])["status"] == "cancelled"
    with pytest.raises(verbs.VerbError, match="unknown argument"):
        verbs.call("run", task="googl-daily", when="now")
    assert "free" in verbs.call("machine")["summary"]


def test_every_verb_has_a_doc_and_a_schema():
    for v in verbs.VERBS.values():
        assert v.doc, v.name
        assert verbs.schema(v)["type"] == "object"
