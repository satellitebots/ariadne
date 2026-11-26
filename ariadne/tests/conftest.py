import pytest

from ariadne import activity, daemon, park, verbs


@pytest.fixture(autouse=True)
def _private_state(tmp_path_factory, monkeypatch):
    """Tests never write to the real activity log or touch the real park flag."""
    d = tmp_path_factory.mktemp("activity")
    monkeypatch.setattr(activity, "LOG_DIR", d)
    monkeypatch.setattr(park, "FLAG", d / "park.json")


@pytest.fixture(autouse=True)
def woken(monkeypatch):
    """Tests never start the real worker. A front installs `daemon.ensure_worker` as the waker; here it only counts,
    and the waker (module state in verbs) is reset for every test."""
    calls = []
    monkeypatch.setattr(daemon, "ensure_worker", lambda: calls.append(1))
    monkeypatch.setattr(verbs, "_waker", None)
    return calls
