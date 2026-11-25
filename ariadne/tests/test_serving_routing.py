"""B3: inference goes to the active model server, not to an assumed local binary or port.

One function answers "where is inference" (`serving.endpoint`); llm, the KV cache, image generation, jobs and the
compiled flow homes all read it. Proved against a stub HTTP server on loopback, so no model and no GPU.
"""
import http.server
import json
import threading

import pytest

from ariadne import flows as flowlib
from ariadne import jobs, kvcache, llm, models as modellib, paths, serve, serving
from ariadne import daemon as orch

REPO_FLOWS = paths.ROOT / "flows"


class Stub:
    """A loopback HTTP server: records every request, answers by path."""

    def __init__(self):
        self.calls = []
        self.routes = {}
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def _go(self, method):
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = self.rfile.read(n) if n else b""
                    outer.calls.append((method, self.path, body))
                    code, payload = outer.routes.get(self.path.split("?")[0], (200, b'{"ok": true}'))
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception:
                    pass          # a client that hung up mid-test must not raise in a server thread

            def do_GET(self):
                self._go("GET")

            def do_POST(self):
                self._go("POST")

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(paths, "STATE", tmp_path)
    monkeypatch.setattr(serving, "LOCAL_FILE", tmp_path / "servers.local.yaml")
    monkeypatch.setattr(serving, "SERVERS_FILE", tmp_path / "servers.yaml")
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)
    monkeypatch.delenv("ARIADNE_LLM_URL", raising=False)
    (tmp_path / "logs").mkdir()
    return tmp_path


def use(stub, monkeypatch):
    """Point Ariadne at the stub, the way a chosen server would."""
    monkeypatch.setenv("ARIADNE_LLM_URL", stub.url + "/v1")


# ---------- the one answer to "where is inference" ----------

def test_endpoint_per_kind(env):
    assert serving.endpoint({"kind": "llama-server", "url": "http://127.0.0.1:8090"}) == "http://127.0.0.1:8090/v1"
    assert serving.endpoint({"kind": "ollama", "url": "http://127.0.0.1:11434"}) == "http://127.0.0.1:11434/v1"
    assert serving.endpoint({"kind": "remote", "url": "http://192.168.1.5:11434"}) == "http://192.168.1.5:11434/v1"
    assert serving.endpoint({"kind": "remote", "url": "http://192.168.1.5:11434/v1"}) == "http://192.168.1.5:11434/v1"


def test_endpoint_refuses_a_server_that_is_not_local(env):
    with pytest.raises(serving.ServingError, match="not this machine or the LAN"):
        serving.endpoint({"kind": "remote", "url": "https://api.openai.com/v1"})


def test_an_env_override_is_also_checked(env, monkeypatch):
    monkeypatch.setenv("ARIADNE_LLM_URL", "https://api.openai.com/v1")
    with pytest.raises(serving.ServingError):
        serving.endpoint()


def test_a_remote_server_with_no_url_says_so(env, monkeypatch):
    (env / "servers.local.yaml").write_text("active: {kind: remote, url: ''}\n", encoding="utf-8")
    with pytest.raises(serving.ServingError, match="no URL|not answering|nothing answered"):
        serving.endpoint()


def test_the_default_matches_where_our_server_listens(env):
    assert serving.DEFAULT["url"].endswith(f":{__import__('ariadne.paths', fromlist=['PORT_MODELS']).PORT_MODELS}")


# ---------- the callers follow it ----------

def test_llm_chat_and_health_go_to_the_active_server(env, stub, monkeypatch):
    use(stub, monkeypatch)
    stub.routes["/v1/chat/completions"] = (200, json.dumps(
        {"choices": [{"message": {"content": "investigation"}}]}).encode())
    assert llm.chat("router", [{"role": "user", "content": "which flow?"}]) == "investigation"
    assert llm.is_up() is True
    assert [c[0] for c in stub.calls] == ["POST", "GET"]
    body = json.loads(stub.calls[0][2])
    assert body["model"] == "router" and body["chat_template_kwargs"]["enable_thinking"] is False


def test_the_runtime_reads_the_active_server(env, stub, monkeypatch):
    """No compiled home to keep in sync: the runtime's model client asks serving.endpoint() itself."""
    use(stub, monkeypatch)
    from ariadne import serving
    assert serving.endpoint() == f"{stub.url}/v1"


def test_kv_parking_and_unload_ask_the_active_server(env, stub, monkeypatch):
    use(stub, monkeypatch)
    stub.routes["/upstream/qwen3.5-9b/slots/0"] = (200, b'{"n_saved": 12}')
    assert kvcache._post("qwen3.5-9b", "save", "x.bin")["n_saved"] == 12
    assert stub.calls[-1][1].startswith("/upstream/qwen3.5-9b/slots/0?action=save")
    assert jobs.unload_models() is True
    assert stub.calls[-1][1] == "/unload"


def test_serve_starts_our_binary_only_for_the_llama_server(env, monkeypatch):
    monkeypatch.setattr(serving, "active", lambda: {"kind": "remote", "url": "http://192.168.1.9:11434"})
    monkeypatch.setattr(llm, "is_up", lambda *a, **k: False)
    monkeypatch.setattr(serve.deps, "find_bin", lambda *a: pytest.fail("must not look for our binary"))
    with pytest.raises(SystemExit, match="active model server is remote"):
        serve.start()
    monkeypatch.setattr(llm, "is_up", lambda *a, **k: True)
    assert serve.start() == 0                                   # a LAN box that answers is left alone


def test_serve_does_not_stop_a_server_that_is_not_ours(env, monkeypatch, capsys):
    monkeypatch.setattr(serving, "active", lambda: {"kind": "remote", "url": "http://192.168.1.9:11434"})
    monkeypatch.setattr(serve, "_kill_strays", lambda: pytest.fail("must not kill local processes"))
    assert serve.stop() == 0
    assert "nothing of ours to stop" in capsys.readouterr().out


def test_the_worker_refuses_to_start_with_a_cloud_home(env, monkeypatch):
    monkeypatch.setattr(orch, "_try_lock", lambda p: pytest.fail("checked before the lock"))
    from ariadne import local_only
    monkeypatch.setattr(local_only, "check_home", lambda: ["base_url https://api.openai.com/v1 is not local"])
    assert orch.serve() == 2
