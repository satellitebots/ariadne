"""The step callback: a client walks a task event by event instead of one coarse wait."""
import time

from ariadne import service, store as storelib


class _DB:
    pass


def test_task_events_filters_by_timestamp(tmp_path):
    db = storelib.Store(tmp_path / "t.db", require_gates=False)
    tid = db.submit("x", "t", "C:/x", "coding", "proj", model="qwen3.6-35b-a3b")
    base = len(service.task_events(tid, 0.0, store=db))
    db.event(tid, "plan", "started")
    time.sleep(0.01)
    db.event(tid, "backbrief", "ready")
    all_ = service.task_events(tid, 0.0, store=db)
    tail = all_[base:]
    assert [e["kind"] for e in tail] == ["plan", "backbrief"]
    assert all_[-1]["ts"] > all_[0]["ts"]
    assert service.task_events(tid, all_[-1]["ts"], store=db) == []


def test_wait_event_returns_once_a_new_event_lands(tmp_path):
    db = storelib.Store(tmp_path / "t.db", require_gates=False)
    tid = db.submit("x", "t", "C:/x", "coding", "proj", model="qwen3.6-35b-a3b")
    db.event(tid, "plan", "started")
    events, t = service.wait_event(tid, 0.0, timeout=3, store=db)
    assert events and events[-1]["kind"] == "plan"
    assert t["id"] == tid