"""The resident-mode switch and what it does to the planner's sleep."""
import pytest


def test_default_is_false_and_unknown_keys_raise(tmp_path, monkeypatch):
    from ariadne import settings
    monkeypatch.setenv("ARIADNE_CONFIG", str(tmp_path / "config.yaml"))
    assert settings.get("orchestrator_resident") is False
    with pytest.raises(KeyError):
        settings.set("not_a_setting", True)


def test_set_round_trips_and_ignores_unknown_keys(tmp_path, monkeypatch):
    from ariadne import settings
    monkeypatch.setenv("ARIADNE_CONFIG", str(tmp_path / "config.yaml"))
    settings.set("orchestrator_resident", True)
    assert settings.get("orchestrator_resident") is True
    (tmp_path / "config.yaml").write_text("orchestrator_resident: false\nnot_a_setting: 1\n", encoding="utf-8")
    assert settings.get("orchestrator_resident") is False


def test_a_broken_config_file_falls_back_to_defaults(tmp_path, monkeypatch):
    from ariadne import settings
    monkeypatch.setenv("ARIADNE_CONFIG", str(tmp_path / "config.yaml"))
    (tmp_path / "config.yaml").write_text("::: not yaml", encoding="utf-8")
    assert settings.get("orchestrator_resident") is False


def test_resident_mode_keeps_the_model_loaded(tmp_path, monkeypatch):
    from ariadne import settings, worker
    monkeypatch.setenv("ARIADNE_CONFIG", str(tmp_path / "config.yaml"))
    settings.set("orchestrator_resident", True)
    w = object.__new__(worker.Worker)
    events = []
    w.unload = lambda: (_ for _ in ()).throw(AssertionError("unload must not be called"))
    w.store = type("S", (), {"event": lambda *a: events.append(a), "_mark": lambda *a: None})()
    w._sleep({"id": "t1"}, "the plan is signed off")
    assert events and events[-1][-1].startswith("orchestrator stays loaded")


def test_default_sleep_unloads_the_model(tmp_path, monkeypatch):
    from ariadne import settings, worker
    monkeypatch.setenv("ARIADNE_CONFIG", str(tmp_path / "config.yaml"))
    settings.set("orchestrator_resident", False)
    w = object.__new__(worker.Worker)
    unloaded = []
    w.unload = lambda: unloaded.append(1) or True
    w.store = type("S", (), {"event": lambda *a: None, "_mark": lambda *a: None})()
    w._sleep({"id": "t1"}, "the plan is signed off")
    assert unloaded == [1]
