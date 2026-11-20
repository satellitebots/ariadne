"""B12 acceptance: a full drill (brief -> backbrief -> sign-off -> execute -> gates) with Hermes absent.

The worker runs on `runtime_run`; the model is a loopback stub that answers by phase and asks for a real tool call, so
this proves the loop, the tool execution in the workspace, the plan/execute split and the gates - end to end, with no
`hermes` binary, no subprocess and no GPU.
"""
import http.server
import json
import threading
from pathlib import Path

import pytest

from ariadne import models as modellib
from ariadne import paths, worker as workerlib
from ariadne.kvcache import NoKVCache
from ariadne.memory import Memory
from ariadne.worker import runtime_run
from ariadne.tests.test_core import env  # noqa: F401 -- env is a fixture
from ariadne.tests.test_worker_session import ONE

PLAN_JSON = ONE[ONE.index("```json"):ONE.index("```", ONE.index("```json") + 7) + 3]


class FakeModel:
    """A model server: a plan when the phase is read-only, otherwise one tool call and then a report."""

    def __init__(self):
        self.requests = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_POST(self):
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n))
                    outer.requests.append({**body, "messages": list(body.get("messages") or [])})
                    messages = body.get("messages") or []
                    system = next((m.get("content") or "" for m in messages if m.get("role") == "system"), "")
                    last_user = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
                    read_only = "READ-ONLY phase" in system
                    tools_done = any(m.get("role") == "tool" for m in messages)
                    if read_only and "CHECKPOINT" in last_user:
                        msg = {"role": "assistant", "content": "SITUATION: planning\nDONE: planned\nOPEN: execute"}
                    elif "This is the PLAN phase" in last_user:
                        msg = {"role": "assistant", "content": "MISSION: the leap year test passes\n\n" + PLAN_JSON}
                    elif not tools_done:
                        msg = {"role": "assistant", "content": "", "tool_calls": [
                            {"id": "call_1", "type": "function",
                             "function": {"name": "terminal", "arguments": json.dumps(
                                 {"command": "echo done > fixed.txt"})}}]}
                    else:
                        msg = {"role": "assistant", "content": "fixed the date test; the tool ran in the workspace"}
                    payload = json.dumps({"choices": [{"message": msg}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception:
                    pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def model(monkeypatch):
    m = FakeModel()
    monkeypatch.setenv("ARIADNE_LLM_URL", m.url)
    monkeypatch.setattr(paths, "HERMES_EXE", Path("C:/definitely/not/hermes.exe"))   # nothing may shell out to it
    yield m
    m.close()


def test_a_task_plans_and_executes_on_our_own_runtime(tmp_path, monkeypatch, model, env):  # noqa: F811
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)
    ws = tmp_path / "ws"
    ws.mkdir()
    w = workerlib.Worker(store=workerlib.Store(env / "t.db", require_gates=False), memory=Memory(env / "m.db"),
                         flows=None, runner=runtime_run, llm_chat=lambda m, msgs: "coding", kv=NoKVCache(),
                         installer=lambda name, cat, log=print: None, on_installed=lambda: None)

    tid = w.store.submit("fix the leap year test", "test", str(ws), flow="coding", session="proj",
                         gates=["run: exit 0"], model="qwen3.6-35b-a3b")
    assert w.run_once()                                    # plan
    t = w.store.get(tid)
    assert t["status"] == "awaiting_signoff" and t["flow"] == "coding"
    assert "the test passes" in t["plan"] and "fix parse_date()" in t["plan"]

    w.store.approve(tid)
    assert w.run_once()                                    # execute + gates
    t = w.store.get(tid)
    assert t["status"] == "done", t["error"] or t["result"]
    assert "fixed the date test" in t["result"]
    assert (ws / "fixed.txt").read_text(encoding="utf-8").strip() == "done"    # the tool really ran

    chats = [b for b in model.requests if "model" in b]        # the KV calls also POST; only chat has a model
    phases = []
    for body in chats:
        system = next((m.get("content") or "" for m in body.get("messages", []) if m.get("role") == "system"), "")
        phases.append("plan" if "READ-ONLY phase" in system else "execute")
    assert "plan" in phases and "execute" in phases

    sessions = list((paths.HOMES / "coding" / "runtime-sessions").glob("*.json"))
    assert sessions, "the runtime should have written its conversation to the flow home"
    assert any("fixed the date test" in json.loads(p.read_text(encoding="utf-8"))["messages"][-1]["content"]
               for p in sessions if json.loads(p.read_text(encoding="utf-8"))["messages"])
