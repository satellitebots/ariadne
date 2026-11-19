"""One document, one rulebook: MCP, chat, terminal and desktop must not be able to disagree."""
import json

import pytest

from ariadne import models as modellib
from ariadne import present, service, tasks_mcp
from ariadne.orchestrator import Store, TaskError


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)
    s = Store(tmp_path / "t.db", require_gates=False)
    monkeypatch.setattr(service, "_store", s)
    monkeypatch.setattr(tasks_mcp, "store", lambda: s)
    return s


def test_service_refuses_a_task_with_no_flow(st):
    with pytest.raises(TaskError, match="name the flow"):
        service.submit("x", source="mcp", model="qwen3.6-35b-a3b")


def test_service_refuses_a_task_with_no_model(st):
    with pytest.raises(TaskError, match="name the model"):
        service.submit("x", source="mcp", flow="coding")


def test_service_refuses_an_unapproved_flow(st):
    with pytest.raises(TaskError, match="not an approved flow"):
        service.submit("x", source="mcp", flow="writing", model="qwen3.6-35b-a3b")


def test_the_mcp_card_is_the_shared_document(st, tmp_path):
    tid = service.submit("fix the leap year test", source="mcp", flow="coding", model="qwen3.6-35b-a3b",
                         workspace=str(tmp_path), gates=["run: pytest -q"])
    t = st.get(tid)
    assert tasks_mcp._view(t).startswith(present.text(t))
    v = present.view(t)
    assert v["label"] == "queued" and v["actions"] == ["cancel"]
    assert "flow: coding" in present.text(t) and "model: qwen3.6-35b-a3b" in present.text(t)


def test_the_page_gets_steps_from_the_plan_not_from_prose(st, tmp_path):
    tid = service.submit("fix the leap year test", source="mcp", flow="coding", model="qwen3.6-35b-a3b",
                         workspace=str(tmp_path), gates=["run: pytest -q"])
    plan = {"mission": "the test passes", "steps": [{"n": 1, "text": "fix parse_date()", "model": "qwen3.6-35b-a3b"}],
            "gates": ["G1 by step 1"], "risks": [], "questions": []}
    st.update(tid, plan_json=json.dumps(plan), plan="MISSION: the test passes\n\nMODEL PLAN\n  task model: x")
    v = present.view(st.get(tid))
    assert v["sections"]["steps"][0]["text"] == "fix parse_date()"
    assert v["sections"]["mission"] == "the test passes"
    assert v["actions"] == ["cancel"]


def test_the_inbox_is_one_text_for_every_surface(st):
    text = present.inbox_text(service.inbox())
    assert text.startswith("worker: ") and "NEEDS YOU" in text and "STOPPED, NO WORKER" in text
