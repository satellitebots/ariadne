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
