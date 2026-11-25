import threading
import time

import pytest

from ariadne.broker import Broker, Busy


class FakeServer:
    def __init__(self, up=True):
        self._up, self.loaded, self.calls = up, [], []

    def up(self):
        return self._up

    def start(self):
        self.calls.append("start")
        self._up = True

    def running(self):
        return list(self.loaded)

    def unload(self):
        self.calls.append("unload")
        self.loaded = []
        return True

    def call(self, model):   # what a holder's model request does to llama-swap: loads it
        self.loaded = [model]


def broker(tmp_path, server=None):
    return Broker(tmp_path / "machine.db", server=server or FakeServer(), poll=0.01)


def test_one_holder_and_a_visible_queue(tmp_path):
    b = broker(tmp_path)
    lease = b.acquire("worker", "run-1", "qwen")
    assert b.status()["holder"]["ref"] == "run-1"
    with pytest.raises(Busy):
        b.acquire("orchestrator", "draft-1", "qwen", wait=False)
    got, seen = [], []
    t = threading.Thread(target=lambda: got.append(
        b.acquire("orchestrator", "draft-1", "gemma", on_wait=seen.append)))
    t.start()
    time.sleep(0.1)
    assert [w["ref"] for w in b.status()["waiting"]] == ["draft-1"] and seen[0]["holder"]["ref"] == "run-1"
    assert "worker run-1 holds the machine" in b.describe()
    lease.release()
    t.join(2)
    assert got and b.status()["holder"]["ref"] == "draft-1" and not b.status()["waiting"]


def test_handoff_unloads_other_weights_but_not_the_same(tmp_path):
    s = FakeServer()
    b = broker(tmp_path, s)
    with b.acquire("worker", "run-1", "qwen"):
        s.call("qwen")
    with b.acquire("orchestrator", "draft-1", "qwen"):   # same weights: a cache switch, no reload
        assert s.calls == [] and s.loaded == ["qwen"]
    with b.acquire("worker", "run-1", "gemma"):          # other weights: unload first
        assert s.calls == ["unload"] and s.loaded == []


def test_a_job_unloads_everything_and_the_server_is_started_by_the_broker(tmp_path):
    s = FakeServer(up=False)
    b = broker(tmp_path, s)
    lease = b.acquire("worker", "run-1", "qwen")
    assert s.calls == ["start"]
    s.call("qwen")
    lease.switch(None, kind="job")
    assert s.loaded == [] and b.status()["holder"]["kind"] == "job"
    lease.release()


def test_a_step_boundary_yields_only_when_someone_waits(tmp_path):
    b = broker(tmp_path)
    lease = b.acquire("worker", "run-1", "qwen")
    assert not lease.boundary() and not lease.yield_turn()
    order = []

    def person():
        with b.acquire("orchestrator", "draft-1", "qwen"):
            order.append("orchestrator")

    t = threading.Thread(target=person)
    t.start()
    time.sleep(0.1)
    assert lease.boundary()
    assert lease.yield_turn()                 # gives it up, the person talks, then it comes back
    order.append("worker again")
    t.join(2)
    assert order == ["orchestrator", "worker again"] and b.status()["holder"]["ref"] == "run-1"
    lease.release()


def test_a_dead_holder_loses_the_lease(tmp_path):
    b = broker(tmp_path)
    with b._conn() as c:   # a worker that crashed while holding the machine (no such process)
        c.execute("INSERT INTO lease(id, kind, ref, model, pid, since) VALUES (1,'worker','run-1','qwen',?,?)",
                  (2**31 - 7, time.time()))
    assert b.holder() is None
    lease = b.acquire("orchestrator", "draft-1", "qwen", wait=False)
    assert b.status()["holder"]["ref"] == "draft-1"
    lease.release()
