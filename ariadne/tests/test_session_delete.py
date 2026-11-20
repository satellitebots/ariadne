"""Deleting a session: a host with tasks is refused; an empty one goes."""
import pytest

from ariadne import service, store as storelib
from ariadne.orchestrator import TaskError


def test_delete_refuses_while_the_session_hosts_tasks(tmp_path):
    db = storelib.Store(tmp_path / "t.db", require_gates=False)
    service.define_session("proj", flow="coding", model="qwen3.6-35b-a3b", store=db)
    service.submit("a task", source="t", flow="coding", model="qwen3.6-35b-a3b",
                   session="proj", workspace="C:/x", store=db)
    with pytest.raises(TaskError, match="holds 1 task"):
        service.delete_session("proj", store=db)


def test_delete_succeeds_when_empty(tmp_path):
    db = storelib.Store(tmp_path / "t.db", require_gates=False)
    service.define_session("proj", flow="coding", model="qwen3.6-35b-a3b", store=db)
    assert service.delete_session("proj", store=db) == {"deleted": "proj"}
    with pytest.raises(TaskError, match="no session named"):
        service.sessions_show("proj", store=db)