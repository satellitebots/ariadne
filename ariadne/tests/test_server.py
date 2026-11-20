"""B9: the server - the verbs from `service`, the views from `present`, SSE, and the static console.

Headless: a TestClient against a temporary store. No server process, no model, no browser.
"""
import json
import re

import pytest
from fastapi.testclient import TestClient

from ariadne import models as modellib
from ariadne import present, service, store as storelib
from ariadne.server import app as server_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)
    st = storelib.Store(tmp_path / "t.db", require_gates=False)
    monkeypatch.setattr(service, "_store", st)
    return TestClient(server_app.create_app(store=st)), st


def give(client, **kw):
    body = {"text": "fix the leap year test", "flow": "coding", "model": "qwen3.6-35b-a3b",
            "workspace": "C:/repos/proj", "gates": ["run: exit 0"], **kw}
    r = client.post("/api/tasks", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- the verbs ----------

def test_health_and_choices(client):
    c, _ = client
    assert c.get("/api/health").json()["ok"] is True
    ch = c.get("/api/choices").json()
    assert [f["name"] for f in ch["flows"]] == ["coding", "content", "design", "investigation"]
    assert any(m["name"] == "qwen3.6-35b-a3b" for m in ch["models"])


def test_a_task_without_a_flow_is_refused_with_the_shared_sentence(client):
    c, _ = client
    r = c.post("/api/tasks", json={"text": "x", "flow": "", "model": "qwen3.6-35b-a3b"})
    assert r.status_code == 400 and r.json()["detail"].startswith("name the flow; approved: coding")
    r = c.post("/api/tasks", json={"text": "x", "flow": "coding", "model": ""})
    assert r.status_code == 400 and "name the model" in r.json()["detail"]


def test_submit_returns_the_same_document_the_terminal_shows(client):
    c, st = client
    doc = give(c)
    assert doc["status"] == "new" and doc["label"] == "queued" and doc["actions"] == ["cancel"]
    assert doc["card"].startswith(present.text(st.get(doc["id"])))
    assert "flow: coding" in doc["card"] and "model: qwen3.6-35b-a3b" in doc["card"]


def test_the_detail_pane_is_the_plan_as_data(client):
    c, st = client
    doc = give(c)
    plan = {"mission": "the test passes", "steps": [{"n": 1, "text": "fix parse_date()", "model": "qwen3.6-35b-a3b"}],
            "gates": ["G1 by step 1"], "risks": [], "questions": []}
    st.update(doc["id"], plan_json=json.dumps(plan), plan="MISSION: the test passes")
    got = c.get(f"/api/tasks/{doc['id']}").json()
    assert got["sections"]["mission"] == "the test passes"
    assert got["sections"]["steps"][0]["text"] == "fix parse_date()"


def test_illegal_verbs_are_refused_by_the_rulebook_not_the_page(client):
    c, st = client
    doc = give(c)
    r = c.post(f"/api/tasks/{doc['id']}/approve", json={"models": ""})
    assert r.status_code == 400 and "this needs one of" in r.json()["detail"]
    assert c.get("/api/tasks/does-not-exist").status_code == 400


def test_sign_off_gates_and_cancel_through_the_api(client):
    c, st = client
    doc = give(c)
    st.update(doc["id"], status="awaiting_signoff", plan="MISSION: x", models=json.dumps(
        {"agent": "qwen3.6-35b-a3b", "steps": [{"n": 1, "text": "fix", "model": "qwen3.6-35b-a3b"}], "notes": []}))
    approved = c.post(f"/api/tasks/{doc['id']}/approve", json={"models": ""}).json()
    assert approved["status"] == "approved" and "approve" not in approved["actions"]

    overview = give(c, text="second")
    st.update(overview["id"], status="awaiting_gates")
    gated = c.post(f"/api/tasks/{overview['id']}/gates", json={"gates": ["run: pytest -q", "README explains it"]})
    assert gated.status_code == 200 and gated.json()["status"] == "new"

    cancelled = c.post(f"/api/tasks/{doc['id']}/cancel").json()
    assert cancelled["status"] == "cancelled" and cancelled["actions"] == []


def test_sessions_list_carries_the_tasks_and_the_waiting_count(client):
    c, st = client
    a = give(c, workspace="C:/repos/proj")
    b = give(c, text="second task", workspace="C:/repos/proj")
    st.update(a["id"], status="awaiting_signoff", plan="MISSION: x")
    rows = c.get("/api/sessions").json()
    assert rows and rows[0]["name"] == "proj" and {t["id"] for t in rows[0]["tasks"]} == {a["id"], b["id"]}
    assert rows[0]["waiting"] == 1
    assert c.get("/api/sessions/proj").json()["name"] == "proj"
    assert c.get("/api/sessions/nope").status_code == 404


def test_the_inbox_names_what_needs_the_person(client):
    c, st = client
    doc = give(c)
    st.update(doc["id"], status="awaiting_signoff", plan="MISSION: x")
    box = c.get("/api/inbox").json()
    assert [t["id"] for t in box["waiting"]] == [doc["id"]]
    assert "NEEDS YOU (1)" in box["text"]


# ---------- the live feed ----------

def test_events_since_streams_frames_with_a_cursor(client):
    c, st = client
    doc = give(c)
    text, cursor = server_app.event_batch(0, store=st)
    assert text.startswith("data: ") and text.endswith("\n\n")
    assert json.loads(text.split("data: ", 1)[1].split("\n\n")[0])["kind"] in ("brief", "gates")
    again, cursor2 = server_app.event_batch(cursor, store=st)
    assert again == "" and cursor2 == cursor                     # nothing new, same cursor
    st.event(doc["id"], "checks", "passed")
    later, _ = server_app.event_batch(cursor, store=st)
    assert "passed" in later


# ---------- the page ----------

def test_the_console_serves_a_built_static_bundle(client):
    c, _ = client
    page = c.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert 'id="root"' in page.text and 'type="module"' in page.text
    m = re.search(r'src="(/static/assets/[^"]+\.js)"', page.text)
    assert m, page.text
    js = c.get(m.group(1))
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert "EventSource" in js.text and "/api/" in js.text


def test_the_console_has_no_capabilities_screen_to_sign_in_from(client):
    """The Hermes shell's /capabilities (providers, connectors, sign-in) is not a route here: it is our app."""
    c, _ = client
    for path in ("/capabilities", "/api/capabilities", "/providers"):
        assert c.get(path).status_code == 404, path


def test_the_bind_is_this_machine_or_the_lan_only():
    assert server_app.check_bind("127.0.0.1") == "127.0.0.1"
    assert server_app.check_bind("192.168.1.20") == "192.168.1.20"
    with pytest.raises(SystemExit, match="not this machine or the LAN"):
        server_app.check_bind("8.8.8.8")
