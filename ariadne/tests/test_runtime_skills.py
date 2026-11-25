"""B12.4: the flow's shared skills as two runtime tools (skills_list, skill_view).

The skill tree is a tmp_path one (flows.shared_skill_dirs is monkeypatched to it); only the model is scripted, as in
test_runtime.py. No network, no GPU.
"""
import pytest

from ariadne import paths, runtime
from ariadne.runtime import session as session_mod
from ariadne.runtime import skills as skills_mod
from ariadne.tests.test_runtime import Script, say, tool_reply

SKILL_ONE = """---
name: one
description: The shared way to do things.
---

# One

The body of the one skill.
"""

SKILL_TWO = """---
name: two
description: The flow's own way.
---

# Two

The body of the two skill.
"""


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A Box on a tmp skills tree: skills/common/one and skills/coding/two."""
    from ariadne import flows as flowlib
    root = tmp_path / "skills"
    (root / "common" / "one").mkdir(parents=True)
    (root / "common" / "one" / "SKILL.md").write_text(SKILL_ONE, encoding="utf-8")
    (root / "coding" / "two").mkdir(parents=True)
    (root / "coding" / "two" / "SKILL.md").write_text(SKILL_TWO, encoding="utf-8")

    def fake_shared_skill_dirs(flow):
        out = {}
        for group in ("common", flow):
            d = root / group
            for p in sorted(d.glob("*/SKILL.md")) if d.exists() else []:
                out[p.parent.name] = p.parent
        return out

    monkeypatch.setattr(flowlib, "shared_skill_dirs", fake_shared_skill_dirs)
    return skills_mod.Box(flowlib.Flow(name="coding", description="d", when="w"))


def test_the_schemas_are_the_two_skill_tools(box):
    offered = box.offered()
    assert [s["function"]["name"] for s in offered] == ["skills_list", "skill_view"]
    assert offered[0]["function"]["parameters"]["required"] == []
    assert offered[1]["function"]["parameters"]["required"] == ["name"]


def test_the_list_gives_name_and_description_for_every_shared_skill(box):
    assert box.call("skills_list", {}) == "- one: The shared way to do things.\n- two: The flow's own way."


def test_the_view_returns_the_skill_body(box):
    out = box.call("skill_view", {"name": "two"})
    assert out.startswith("---") and "The body of the two skill." in out


def test_an_unknown_skill_is_an_error_that_names_the_available_ones(box):
    out = box.call("skill_view", {"name": "nope"})
    assert out.startswith("ERROR: no skill 'nope'") and "one, two" in out


def test_a_named_flow_is_looked_up_in_that_flow(box):
    assert "The body of the one skill." in box.call("skill_view", {"name": "one", "flow": "design"})
    assert box.call("skill_view", {"name": "two", "flow": "design"}).startswith("ERROR: no skill 'two'")
    assert box.call("skills_list", {"flow": "design"}) == "- one: The shared way to do things."


def test_the_loop_dispatches_skill_calls_to_the_box(tmp_path, box):
    home = tmp_path / "home"
    run = Script(tool_reply("skill_view", {"name": "two"}), say("I read it and will follow it"))
    answer = runtime.run("plan it", home=home, workspace=str(tmp_path), phase="plan", model="m",
                         session="k1", transport=run, skills=box)
    assert (answer.text, answer.stopped) == ("I read it and will follow it", "")
    tool_msg = [m for m in session_mod.load(home, "k1") if m.get("role") == "tool"][0]
    assert tool_msg["name"] == "skill_view" and "The body of the two skill." in tool_msg["content"]
    names = [t["function"]["name"] for t in run.calls[0]["tools"]]
    assert "skills_list" in names and "skill_view" in names   # offered on the wire


