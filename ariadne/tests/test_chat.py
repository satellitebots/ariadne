"""B10: our own chat - a session-bound conversation that can talk and submit, and cannot do the work.

The construction is the toolset list (no files, terminal, code or browser), so the tests check that list and the turn,
with a fake runner: no model, no Hermes process.
"""
import json

import pytest
from fastapi.testclient import TestClient

from ariadne import chat, models as modellib
from ariadne import paths, service, store as storelib
from ariadne.server import app as server_app


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)
    monkeypatch.delenv("ARIADNE_LLM_URL", raising=False)
    st = storelib.Store(tmp_path / "t.db", require_gates=False)
    monkeypatch.setattr(service, "_store", st)
    return st


class Turn:
    def __init__(self, text="It plans to fix the test; submit it and sign off.", code=0):
        self.text, self.code, self.calls = text, code, []

    def __call__(self, home, prompt, session="", model=""):
        self.calls.append({"home": home, "prompt": prompt, "session": session, "model": model})
        from ariadne.worker import RunResult
        return RunResult(self.text, self.code, "log")


def test_the_chat_has_no_doing_tools_by_construction(env, monkeypatch):
    from ariadne import runtime
    from ariadne.runtime import mcp as mcp_mod
    captured = {}

    class FakePool:
        def __init__(self, cfg, **kw):
            self.cfg, self.closed = cfg, False

        def offered(self, read_only=False):
            return []

        def call(self, *a, **k):
            return "ERROR: none"

        def close(self, wait=5):
            self.closed = True

    monkeypatch.setattr(mcp_mod, "Pool", FakePool)

    def fake_run(*a, **kw):
        captured.update(kw)
        return runtime.Answer(text="ok")

    monkeypatch.setattr(runtime, "run", fake_run)
    assert chat.run_turn(chat.chat_home(), "p", "s", "m").text == "ok"
    assert captured["native_tools"] is False                       # no file, patch, search or terminal tools at all
    assert captured["system"] == chat.CHAT_SYSTEM
    assert "ariadne_tasks" in captured["mcp"].cfg and captured["mcp"].closed
    assert captured["mcp"].cfg["ariadne_tasks"]["args"] == ["-m", "ariadne.tasks_mcp"]


def test_a_turn_carries_the_session_the_rule_and_the_person_words(env):
    st = env
    tid = service.submit("fix the leap year test", source="ui", flow="coding", model="qwen3.6-35b-a3b",
                         workspace="C:/repos/proj", session="proj", gates=["run: exit 0"])
    run = Turn()
    reply = chat.ask("what is happening in this session?", session="proj", store=st, runner=run)
    assert reply.startswith("It plans to fix")
    prompt = run.calls[0]["prompt"]
    assert 'session "proj"' in prompt and "what is happening in this session?" in prompt
    assert tid in prompt and "cannot do the work yourself" in prompt
    assert run.calls[0]["session"] == "proj"


def test_an_empty_message_is_refused_before_a_model_is_called(env):
    run = Turn()
    with pytest.raises(chat.ChatError, match="say something first"):
        chat.ask("   ", store=env, runner=run)
    assert run.calls == []


def test_a_model_that_does_not_answer_is_an_error_not_a_blank_reply(env):
    with pytest.raises(chat.ChatError, match="did not answer"):
        chat.ask("hi", store=env, runner=Turn(text="", code=1))


def test_the_context_is_the_task_store_not_a_file(env):
    st = env
    assert "no tasks yet" in chat.session_context("empty-session", store=st)
    service.submit("write the report", source="ui", flow="content", model="gemma-4-12b",
                   workspace="C:/repos/blog", session="blog", gates=["the post is 800 words"])
    ctx = chat.session_context("blog", store=st)
    assert 'Session "blog"' in ctx and "write the report" in ctx and "new" in ctx


def test_the_console_posts_one_turn_and_reports_a_refusal_as_400(env):
    st = env
    c = TestClient(server_app.create_app(store=st, chat_runner=Turn()))
    r = c.post("/api/chat", json={"message": "what is queued?", "session": "proj"})
    assert r.status_code == 200 and r.json()["reply"].startswith("It plans")
    bad = TestClient(server_app.create_app(store=st, chat_runner=Turn(text="", code=1)))
    r = bad.post("/api/chat", json={"message": "hi", "session": "proj"})
    assert r.status_code == 400 and "did not answer" in r.json()["detail"]
    assert c.post("/api/chat", json={"message": "  "}).status_code == 400


def test_the_page_has_the_chat_and_says_what_it_cannot_do(env):
    c = TestClient(server_app.create_app(store=env))
    page = c.get("/").text
    assert 'id="chat-form"' in page and "it cannot do one" in page
    js = c.get("/static/app.js").text
    assert "/api/chat" in js and "chat-form" in js
