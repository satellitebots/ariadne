import pytest

from ariadne import desktop


def _tree(tmp_path, text):
    f = tmp_path / "apps" / "x.ts"
    f.parent.mkdir(parents=True)
    f.write_text(text, encoding="utf-8")
    return f


def test_overlay_applies_when_counts_match(tmp_path):
    f = _tree(tmp_path, "Hermes Desktop says Hermes Desktop")
    desktop.apply(tmp_path, {"edits": [{"file": "apps/x.ts", "old": "Hermes Desktop", "new": "Ariadne", "count": 2,
                                        "why": "name"}], "assets": {}})
    assert f.read_text(encoding="utf-8") == "Ariadne says Ariadne"


def test_overlay_refuses_partial_application(tmp_path):
    f = _tree(tmp_path, "Hermes Desktop once")
    edits = [{"file": "apps/x.ts", "old": "once", "new": "twice", "count": 1, "why": "a"},
             {"file": "apps/x.ts", "old": "Hermes Desktop", "new": "Ariadne", "count": 2, "why": "b"}]
    with pytest.raises(SystemExit, match="expected 2 match"):
        desktop.apply(tmp_path, {"edits": edits, "assets": {}})
    assert f.read_text(encoding="utf-8") == "Hermes Desktop once"  # nothing written
