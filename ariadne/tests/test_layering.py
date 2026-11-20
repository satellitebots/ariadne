"""B5: the store lives in `store.py`, and no surface calls it - every door goes through `service.py`.

Not a behaviour test: it holds the layering the design asks for, so a later edit cannot quietly give a surface its
own store access back.
"""
from pathlib import Path

from ariadne import __main__ as cli
from ariadne import console, flows as flowlib, orchestrator, park, service, store, tasks_mcp, worker
from ariadne import models as modellib
from ariadne import paths
from ariadne.memory import Memory

REPO_FLOWS = paths.ROOT / "flows"


def test_the_store_has_its_own_module():
    assert hasattr(store, "Store") and hasattr(store, "SCHEMA") and hasattr(store, "parse_gates")
    src = Path(orchestrator.__file__).read_text(encoding="utf-8")
    assert "class Store" not in src and "CREATE TABLE" not in src
    assert len(src.splitlines()) < 420                     # it is the loop and the CLI now, not the store


def test_no_surface_reaches_for_a_store():
    for surface in (console, tasks_mcp, park, cli):
        assert not hasattr(surface, "Store"), surface.__name__
        src = Path(surface.__file__).read_text(encoding="utf-8")
        assert "store.get(" not in src and "store.list(" not in src and "store.update(" not in src, surface


def test_the_worker_still_records_its_own_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)
    st = store.Store(tmp_path / "t.db", require_gates=False)
    w = worker.Worker(store=st, memory=Memory(tmp_path / "m.db"), flows=flowlib.load_flows(REPO_FLOWS),
                      runner=lambda *a, **k: None)
    assert w.store is st                                    # the engine writes; the surfaces ask service


def test_every_surface_verb_is_the_same_function(tmp_path, monkeypatch):
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)
    st = store.Store(tmp_path / "t.db", require_gates=False)
    monkeypatch.setattr(service, "_store", st)
    tid = service.submit("fix the leap year test", source="cli", flow="coding", model="qwen3.6-35b-a3b",
                         workspace=str(tmp_path), gates=["run: exit 0"])
    assert service.task(tid)["status"] == "new"
    assert [t["id"] for t in service.tasks()] == [tid]
    st.update(tid, status="awaiting_signoff")              # as if a backbrief were ready
    assert service.approve(tid)["status"] == "approved"
    service.cancel(tid)
    assert service.task(tid)["status"] == "cancelled"


def test_the_one_gesture_is_the_only_route_that_does_not_name_a_flow(tmp_path, monkeypatch):
    st = store.Store(tmp_path / "t.db", require_gates=False)
    monkeypatch.setattr(service, "_store", st)
    tid = service.submit_unrouted("fix the date test", source="cli", workspace=str(tmp_path), session="proj")
    t = service.task(tid)
    assert t["flow"] == "" and t["session"] == "proj"       # no flow yet: the worker's router must pick one


def test_the_cli_submit_requires_a_flow_and_a_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)
    monkeypatch.setattr(orchestrator, "_default_workspace", lambda: str(tmp_path))
    from ariadne import service as svc
    monkeypatch.setattr(svc, "_store", store.Store(tmp_path / "t.db", require_gates=False))
    assert orchestrator.main(["submit", "fix it"]) == 2                 # no flow: refused, not routed
    assert "name the flow" in capsys.readouterr().out
    assert orchestrator.main(["submit", "fix it", "--flow", "coding"]) == 2
    assert "name the model" in capsys.readouterr().out
