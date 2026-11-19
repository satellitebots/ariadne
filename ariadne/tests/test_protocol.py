"""The plan is data: one parser, one renderer, and the prose fallback says so."""
import pytest

from ariadne import protocol, render

PLAN = """MISSION: the leap-year test passes

```json
{"mission": "the leap-year test passes",
 "steps": [{"n": 1, "text": "fix parse_date()"}, {"n": 2, "text": "add a regression test"}],
 "gates": ["pytest -q passes at step 2"], "risks": ["other date parsing may share the bug"],
 "questions": []}
```
"""


def test_parses_the_fenced_block_and_fills_the_task_model():
    p = protocol.parse(PLAN, "qwen3.6-35b-a3b")
    assert [s["n"] for s in p["steps"]] == [1, 2]
    assert all(s["model"] == "qwen3.6-35b-a3b" for s in p["steps"])
    assert p["gates"] == ["pytest -q passes at step 2"]


def test_rejects_a_plan_with_no_block():
    with pytest.raises(protocol.PlanError, match="no JSON plan block"):
        protocol.parse("MISSION: something\nSTEPS:\n1. do it\n")


def test_rejects_unknown_keys_so_a_hallucinated_schema_is_caught():
    bad = '```json\n{"mission": "x", "steps": [{"n": 1, "text": "y"}], "budget": 3}\n```'
    with pytest.raises(protocol.PlanError, match="unknown plan keys: budget"):
        protocol.parse(bad)


def test_rejects_a_plan_with_no_steps():
    with pytest.raises(protocol.PlanError, match="no steps"):
        protocol.parse('```json\n{"mission": "x", "steps": []}\n```')


def test_render_is_the_document_both_surfaces_show():
    p = protocol.parse(PLAN, "qwen3.6-35b-a3b")
    doc = render.backbrief(p)
    for line in ("MISSION:", "STEPS:", "GATES:", "RISKS:", "QUESTIONS:", "1. fix parse_date()"):
        assert line in doc
    assert render.steps(p)[1]["text"] == "add a regression test"


def test_plan_survives_a_round_trip_through_json():
    p = protocol.parse(PLAN, "qwen3.6-35b-a3b")
    again = protocol.from_json(protocol.to_json(p))
    assert again and again["steps"] == p["steps"]
