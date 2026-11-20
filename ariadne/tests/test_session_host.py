"""A session is the host; tasks are executions inside it; one model, one thing at a time."""
import pytest

from ariadne import service, store as storelib
from ariadne.orchestrator import TaskError


@pytest.fixture
def db(tmp_path):
    return storelib.Store(tmp_path / "t.db", require_gates=False)


def test_a_session_exists_before_any_task_and_holds_its_pivot(db):
    s = service.define_session("proj", flow="coding", model="qwen3.6-35b-a3b", workspace="C:/repos/proj", store=db)
    assert s["name"] == "proj" and s["flow"] == "coding"
    assert s["model"] == "qwen3.6-35b-a3b" and s["workspace"] == "C:/repos/proj"
    assert s["tasks"] == []


def test_many_tasks_share_one_session(db):
    service.define_session("proj", flow="coding", model="qwen3.6-35b-a3b", workspace="C:/repos/proj", store=db)
    service.submit("fix the date test", source="t", flow="coding", model="qwen3.6-35b-a3b",
                   session="proj", workspace="C:/repos/proj", store=db)
    service.submit("add the export command", source="t", flow="coding", model="qwen3.6-35b-a3b",
                   session="proj", workspace="C:/repos/proj", store=db)
    assert len(service.sessions_show("proj", store=db)["tasks"]) == 2
    assert len(db.sessions()) == 1


def test_a_task_may_override_the_pivot_without_mutating_the_session(db):
    service.define_session("proj", flow="coding", model="qwen3.6-35b-a3b", workspace="C:/repos/proj", store=db)
    task = db.get(service.submit("draw the diagram", source="t", flow="design", model="qwen3.6-35b-a3b",
                                 session="proj", workspace="C:/repos/proj", store=db))
    assert task["flow"] == "design"
    s = service.sessions_show("proj", store=db)
    assert s["flow"] == "coding" and s["model"] == "qwen3.6-35b-a3b"


def test_claim_takes_oldest_created_not_most_recently_touched(db):
    t1 = db.submit("first", "t", "C:/x", "coding", "proj", model="qwen3.6-35b-a3b")
    t2 = db.submit("second", "t", "C:/x", "coding", "proj", model="qwen3.6-35b-a3b")
    db.update(t2, plan="touch")   # bumps `updated`; a bad claim order would take t2 next
    claimed = db.claim_next()
    assert claimed["id"] == t1


def test_the_busy_gate_refuses_while_a_worker_runs(tmp_path, db, monkeypatch):
    from ariadne import settings
    import ariadne.orchestrator as orch
    monkeypatch.setenv("ARIADNE_CONFIG", str(tmp_path / "config.yaml"))
    settings.set("orchestrator_resident", False)
    tid = db.submit("long task", "t", "C:/x", "coding", "proj", model="qwen3.6-35b-a3b")
    db.update(tid, status="executing")
    monkeypatch.setattr(orch, "worker_running", lambda: True)
    with pytest.raises(TaskError, match="hardware occupied"):
        service.submit("another", source="t", flow="coding", model="qwen3.6-35b-a3b",
                       session="proj", workspace="C:/x", store=db)
    with pytest.raises(TaskError, match="hardware occupied"):
        service.define_session("newproj", flow="coding", store=db)


def test_resident_mode_lifts_the_gate(tmp_path, db, monkeypatch):
    from ariadne import settings
    import ariadne.orchestrator as orch
    monkeypatch.setenv("ARIADNE_CONFIG", str(tmp_path / "config.yaml"))
    settings.set("orchestrator_resident", True)
    tid = db.submit("long task", "t", "C:/x", "coding", "proj", model="qwen3.6-35b-a3b")
    db.update(tid, status="executing")
    monkeypatch.setattr(orch, "worker_running", lambda: True)
    service.submit("another", source="t", flow="coding", model="qwen3.6-35b-a3b",
                   session="proj", workspace="C:/x", store=db)
    assert len(service.sessions_show("proj", store=db)["tasks"]) == 2


def test_no_worker_no_gate(db):
    tid = db.submit("long task", "t", "C:/x", "coding", "proj", model="qwen3.6-35b-a3b")
    db.update(tid, status="executing")
    # worker_running() is False by default in tests (no lock file): create freely
    service.submit("another", source="t", flow="coding", model="qwen3.6-35b-a3b",
                   session="proj", workspace="C:/x", store=db)