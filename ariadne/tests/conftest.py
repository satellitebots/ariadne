import pytest

from ariadne import activity, park


@pytest.fixture(autouse=True)
def _private_state(tmp_path_factory, monkeypatch):
    """Tests never write to the real activity log or touch the real park flag."""
    d = tmp_path_factory.mktemp("activity")
    monkeypatch.setattr(activity, "LOG_DIR", d)
    monkeypatch.setattr(park, "FLAG", d / "park.json")
