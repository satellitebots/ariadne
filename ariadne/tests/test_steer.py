"""Steering and the optional workspace: the two workflow gaps that made a task hard to live with."""
import pytest

from ariadne import service, store as storelib
from ariadne.errors import TaskError
from ariadne.tests.test_core import REPO_FLOWS, FakeRunner, env, make_worker  # noqa: F401 -- env is a fixture


def test_a_steer_is_queued_once_and_delivered_once(env):  # noqa: F811
    st = storelib.Store(env / "s.db")
    tid = st.submit("do it", "test", str(env))
    st.steer(tid, "use pytest, not unittest")
    assert st.take_steers(tid) == ["use pytest, not unittest"]
    assert st.take_steers(tid) == []                       # delivered, not repeated


def test_a_finished_task_cannot_be_steered(env):  # noqa: F811
    st = storelib.Store(env / "s.db")
    tid = st.submit("do it", "test", str(env))
    st.update(tid, status="done")
    with pytest.raises(TaskError, match="nothing left to steer"):
        st.steer(tid, "too late")


def test_a_steer_reaches_the_next_execute_prompt(env):  # noqa: F811
    run = FakeRunner()
    w = make_worker(env, run)
    tid = w.store.submit("fix it", "test", str(env), flow="coding", model="qwen3.6-35b-a3b",
                         gates=["run: exit 0"])
    assert w.run_once()                                     # plan
    assert w.store.get(tid)["status"] == "awaiting_signoff"
    w.store.approve(tid)
    w.store.steer(tid, "use pytest, not unittest")
    assert w.run_once()                                     # execute + gates
    executes = [c[2] for c in run.calls if c[1] == "execute"]
    assert executes and "STEERING" in executes[0] and "use pytest" in executes[0]
    assert w.store.get(tid)["status"] == "done"


def test_the_workspace_is_optional_and_a_session_remembers_it(tmp_path, monkeypatch):
    st = storelib.Store(tmp_path / "t.db", require_gates=False)
    monkeypatch.setattr(service, "_store", st)
    first = service.submit("one", source="test", flow="coding", model="qwen3.6-35b-a3b",
                           workspace=str(tmp_path / "proj"), session="proj")
    second = service.submit("two", source="test", flow="coding", model="qwen3.6-35b-a3b", session="proj")
    assert service.task(first, store=st)["workspace"] == str(tmp_path / "proj")
    assert service.task(second, store=st)["workspace"] == str(tmp_path / "proj")   # no workspace given


def test_a_brand_new_task_without_a_workspace_uses_the_current_folder(tmp_path, monkeypatch):
    st = storelib.Store(tmp_path / "t.db", require_gates=False)
    monkeypatch.setattr(service, "_store", st)
    monkeypatch.chdir(tmp_path)
    tid = service.submit("one", source="test", flow="coding", model="qwen3.6-35b-a3b")
    assert service.task(tid, store=st)["workspace"] == str(tmp_path)
