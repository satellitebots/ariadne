"""The overlay: our modules win over the pinned Hermes checkout, without editing the submodule.

The mechanism is sys.path order plus a prepended package path; the ledger is overlay.yaml. These tests drive both with
a synthetic package pair, so they prove the machinery without owning a real Hermes module yet.
"""
import sys

import pytest

from ariadne import overlay, paths


def test_install_puts_the_root_and_the_checkout_first_and_is_idempotent(tmp_path):
    before = list(sys.path)
    try:
        order = overlay.install(root=tmp_path / "root", hermes=tmp_path / "hermes")
        assert [str(p) for p in order] == sys.path[:2]
        overlay.install(root=tmp_path / "root", hermes=tmp_path / "hermes")
        assert sys.path.count(str(tmp_path / "root")) == 1
        assert sys.path.count(str(tmp_path / "hermes")) == 1
    finally:
        sys.path[:] = before


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    """An 'upstream' package and an overlay that adds one module to it."""
    upstream = tmp_path / "upstream"
    (upstream / "demo").mkdir(parents=True)
    (upstream / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (upstream / "demo" / "base.py").write_text('VALUE = "upstream"\n', encoding="utf-8")
    over = tmp_path / "overlay"
    (over / "demo").mkdir(parents=True)
    (over / "demo" / "extra.py").write_text('VALUE = "overlay"\n', encoding="utf-8")
    monkeypatch.syspath_prepend(str(upstream))
    for name in [n for n in sys.modules if n == "demo" or n.startswith("demo.")]:
        sys.modules.pop(name, None)                            # forget any earlier import
    yield upstream, over
    for name in [n for n in sys.modules if n == "demo" or n.startswith("demo.")]:
        sys.modules.pop(name, None)


def test_an_overlaid_module_wins_and_the_rest_still_comes_from_upstream(synthetic):
    _upstream, over = synthetic
    import demo
    assert overlay.extend("demo", over) is True
    from demo import extra
    from demo import base
    assert extra.VALUE == "overlay" and base.VALUE == "upstream"
    assert str(over / "demo") == demo.__path__[0]


def test_apply_installs_and_extends_every_package(synthetic, tmp_path):
    _upstream, over = synthetic
    applied = overlay.apply(overlay_dir=over, hermes=tmp_path / "hermes")
    assert applied == ["demo"] and "demo" in sys.modules


def test_a_package_with_no_overlay_is_not_touched(synthetic):
    _upstream, _over = synthetic
    assert overlay.extend("demo", synthetic[0] / "nothing") is False


def test_the_ledger_names_a_file_a_reason_and_a_test(tmp_path):
    over = tmp_path / "overlay"
    (over / "tools").mkdir(parents=True)
    (over / "tools" / "example.py").write_text("", encoding="utf-8")
    good = tmp_path / "overlay.yaml"
    good.write_text("overrides:\n  - module: tools.example\n    why: we need X\n"
                    "    test: ariadne/tests/test_overlay.py::test_x\n", encoding="utf-8")
    assert overlay.check(path=good, overlay_dir=over) == []
    bad = tmp_path / "bad.yaml"
    bad.write_text("overrides:\n  - module: tools.missing\n    why: ''\n", encoding="utf-8")
    problems = overlay.check(path=bad, overlay_dir=over)
    assert any("no file" in p for p in problems) and any("no reason" in p for p in problems)
    assert any("no test" in p for p in problems)


def test_the_real_ledger_is_consistent():
    assert overlay.check() == []
    assert overlay.MANIFEST.exists()
    assert paths.UPSTREAM.name == "hermes"
