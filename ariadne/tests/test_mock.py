"""The mock backend: real verbs, store, engine and broker, scripted worker and orchestrator, no model."""
import threading
import time

from ariadne import mock, permissions, verbs


def _wait(pred, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_the_mock_runs_asks_and_answers_without_a_model(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "ASKS", tmp_path / "asks")
    ctx, eng = mock.build(tmp_path)
    eng.eng.step_runner.pace = 0.0
    eng.eng.job_runner = lambda j, db, **kw: mock.jobs.run(j, db, unload=lambda: True, poll=0.05, **kw)
    assert {t["name"] for t in verbs.call("tasks")} >= {"googl-daily", "competitor-scan", "dependency-audit"}
    assert {r["status"] for r in verbs.call("runs")} >= {"done", "needs_you", "cancelled", "failed", "queued"}
    assert len(verbs.call("drafts")) == 2

    assert eng.eng.run_once()                                     # competitor-scan: five steps, a job, reviews
    scan = next(r for r in verbs.call("runs") if r["task"] == "competitor-scan" and r["trigger"] == "manual")
    assert scan["status"] == "done", scan["error"]
    p = verbs.call("progress", run=scan["id"])
    assert p["tool_calls"] > 5 and p["model_calls"] > 3 and verbs.call("run_show", run=scan["id"])["jobs"]

    t = threading.Thread(target=eng.eng.run_once, daemon=True)  # dependency-audit asks before git push
    t.start()
    audit = lambda: next(r for r in verbs.call("runs", live=True) if r["task"] == "dependency-audit")
    assert _wait(lambda: audit()["status"] == "asking")
    assert "git push origin main" in audit()["ask"]["text"]
    verbs.call("approve", run=audit()["id"])
    t.join(20)
    done = next(r for r in verbs.call("runs") if r["task"] == "dependency-audit" and r["trigger"] == "manual")
    assert done["status"] == "done"

    reply = ctx.orchestrator.turn("c-test", "what is running?", store=ctx.store, flows=ctx.flows,
                                  catalog=ctx.catalog, broker=ctx.broker)
    assert reply.startswith("(mock orchestrator)")
    assert verbs.call("chat_activity", conversation="c-test")       # its work is shown, as for the real one
    assert verbs.call("rules")["recipe"][0]["id"] == "W1"

    # a template-less draft can be completed from the form alone, then signed
    d = next(x for x in verbs.call("drafts") if x["flow"] == "coding")
    d = verbs.call("draft_fill", draft=d["id"], name="csv-export", workspace=str(tmp_path / "work" / "csv"),
                   trigger="0 8 * * 1", params={"change": "The member list exports to CSV",
                                                "done_when": "pytest tests/test_export.py passes"})
    assert d["ready"], d["problems"]
    t = verbs.call("sign", draft=d["id"])
    assert t["name"] == "csv-export" and "Monday" in t["trigger"] or "1" in t["trigger"]


def test_the_mock_shows_a_planned_task_expanding_into_one_step_per_item(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "ASKS", tmp_path / "asks")
    ctx, eng = mock.build(tmp_path)
    eng.eng.step_runner.pace = 0.0
    for r in verbs.call("runs", live=True):      # the seed's queue (one of them waits for an approval)
        verbs.call("cancel", run=r["id"])
    guide = next(t for t in verbs.call("tasks") if t["name"] == "ga-study-guide")
    r = verbs.call("run", task=guide["id"])
    while eng.eng.run_once():
        pass
    v = verbs.call("run_show", run=r["id"])
    assert v["status"] == "done", v["error"]
    titles = [s["title"] for s in v["steps"]]
    assert v["steps_total"] == len(mock.MOCK_PLAN) + 2 and titles[0] == "Outline from the sources"
    assert titles[1].startswith("Write 1/7: Exam format") and titles[-1] == "Assemble and check"
    text = (tmp_path / "work" / "ga-guide" / "GUIDE.md").read_text(encoding="utf-8")
    assert text.count("\n## ") == len(mock.MOCK_PLAN)
