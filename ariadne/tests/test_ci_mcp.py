"""B6c: the `ci` MCP server - Jenkins, GitHub Actions and GitLab, against a stub server (no network, no model)."""
import http.server
import io
import json
import threading
import zipfile

import pytest

from ariadne import ci_mcp


class Stub:
    """A loopback HTTP server: records (method, path, headers, body), answers by path prefix."""

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
                    outer.calls.append({"method": method, "path": self.path,
                                        "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                    star = max((k for k in outer.routes if self.path.split("?")[0].startswith(k)), key=len, default="")
                    code, payload = outer.routes.get(star, (404, b'{"message": "not found"}'))
                    if isinstance(payload, str):
                        payload = payload.encode()
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception:
                    pass

            def do_GET(self):
                self._go("GET")

            def do_POST(self):
                self._go("POST")

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def last(self):
        return self.calls[-1]

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.close()


@pytest.fixture
def ci(tmp_path, monkeypatch, stub):
    cfg = tmp_path / "ci.yaml"
    cfg.write_text(
        "pipelines:\n"
        f"  build:\n    provider: github\n    repo: me/app\n    workflow: ci.yml\n    ref: main\n"
        f"    token_env: GH_TOKEN\n    api: {stub.url}\n"
        f"  gl:\n    provider: gitlab\n    project: grp/app\n    ref: main\n    token_env: GL_TOKEN\n"
        f"    api: {stub.url}\n"
        f"  jenkins:\n    provider: jenkins\n    url: {stub.url}\n    repo: team/app\n    ref: main\n"
        f"    token_env: JK_TOKEN\n    user_env: JK_USER\n"
        "  notoken:\n    provider: github\n    repo: me/app\n    workflow: ci.yml\n",
        encoding="utf-8")
    monkeypatch.setattr(ci_mcp, "CONFIG", cfg)
    monkeypatch.setenv("GH_TOKEN", "gh-secret")
    monkeypatch.setenv("GL_TOKEN", "gl-secret")
    monkeypatch.setenv("JK_TOKEN", "jk-secret")
    monkeypatch.setenv("JK_USER", "alice")
    return cfg


def test_pipelines_lists_what_is_configured_and_whether_the_token_is_set(ci, monkeypatch):
    rows = json.loads(ci_mcp.ci_pipelines())
    by = {r["name"]: r for r in rows}
    assert by["build"]["provider"] == "github" and by["build"]["token"] == "$GH_TOKEN set"
    assert by["notoken"]["token"] == "(none named)"
    monkeypatch.delenv("GL_TOKEN")
    assert {r["name"]: r for r in json.loads(ci_mcp.ci_pipelines())}["gl"]["token"] == "$GL_TOKEN NOT set"


def test_github_status_reads_the_runs(ci, stub):
    stub.routes["/repos/me/app/actions/runs"] = (200, json.dumps({"workflow_runs": [
        {"run_number": 42, "id": 9, "head_branch": "main", "event": "push", "status": "completed",
         "conclusion": "failure", "html_url": "http://x/42"}]}))
    rows = json.loads(ci_mcp.ci_status("build", limit=3))
    assert rows == [{"run": 42, "id": 9, "branch": "main", "event": "push", "status": "completed",
                     "conclusion": "failure", "url": "http://x/42"}]
    call = stub.last()
    assert call["path"].startswith("/repos/me/app/actions/runs?per_page=3")
    assert call["headers"]["authorization"] == "Bearer gh-secret"


def test_github_trigger_posts_the_workflow_and_ref(ci, stub):
    stub.routes["/repos/me/app/actions/workflows"] = (204, b"")
    out = json.loads(ci_mcp.ci_trigger("build", ref="release"))
    assert "me/app/ci.yml on release" in out["triggered"]
    call = stub.last()
    assert call["method"] == "POST" and call["path"] == "/repos/me/app/actions/workflows/ci.yml/dispatches"
    assert json.loads(call["body"]) == {"ref": "release"}


def test_github_logs_come_out_of_the_zip(ci, stub):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("build/1_test.txt", "step 1 ok\nstep 2 FAILED: assertion\n")
    stub.routes["/repos/me/app/actions/runs/9/logs"] = (200, buf.getvalue())
    text = ci_mcp.ci_logs("build", run="9", lines=5)
    assert "step 2 FAILED" in text and "--- build/1_test.txt ---" in text


def test_gitlab_status_trigger_and_trace(ci, stub):
    stub.routes["/projects/grp%2Fapp/pipelines"] = (200, json.dumps([
        {"id": 7, "iid": 3, "ref": "main", "status": "failed", "web_url": "http://gl/3"}]))
    assert json.loads(ci_mcp.ci_status("gl"))[0] == {"run": 3, "id": 7, "branch": "main", "status": "failed",
                                                     "url": "http://gl/3", "created": None}
    assert stub.last()["headers"]["private-token"] == "gl-secret"

    stub.routes["/projects/grp%2Fapp/pipeline"] = (201, json.dumps({"id": 8, "iid": 4, "status": "created"}))
    out = json.loads(ci_mcp.ci_trigger("gl"))
    assert out["run"] == 4 and json.loads(stub.last()["body"]) == {"ref": "main"}

    stub.routes["/projects/grp%2Fapp/jobs"] = (200, json.dumps([
        {"id": 55, "name": "test", "status": "failed", "pipeline": {"id": 8}}]))
    stub.routes["/projects/grp%2Fapp/jobs/55/trace"] = (200, "line1\nline2 FAILED\n")
    text = ci_mcp.ci_logs("gl", run="8")
    assert "job test (failed)" in text and "line2 FAILED" in text


def test_jenkins_status_and_console_text(ci, stub):
    stub.routes["/job/team/job/app/api/json"] = (200, json.dumps({"builds": [
        {"number": 12, "result": None, "url": "http://jk/12", "duration": 1000, "builtOn": "node1"}]}))
    rows = json.loads(ci_mcp.ci_status("jenkins"))
    assert rows == [{"run": 12, "result": "running", "url": "http://jk/12", "duration_ms": 1000,
                     "built_on": "node1"}]
    headers = stub.last()["headers"]
    assert headers["authorization"].startswith("Basic ")          # user:token, base64
    import base64
    assert base64.b64decode(headers["authorization"].split()[1]).decode() == "alice:jk-secret"

    stub.routes["/job/team/job/app/lastBuild/consoleText"] = (200, "one\ntwo\nTHREE\n")
    assert ci_mcp.ci_logs("jenkins", lines=2) == "two\nTHREE"


def test_jenkins_trigger_with_parameters(ci, stub):
    stub.routes["/job/team/job/app/buildWithParameters"] = (201, b"")
    out = json.loads(ci_mcp.ci_trigger("jenkins", params={"env": "staging"}))
    assert out["status"] == 201
    call = stub.last()
    assert call["path"].endswith("/buildWithParameters") and b"env=staging" in call["body"]


def test_a_missing_token_names_the_variable(ci, monkeypatch):
    monkeypatch.delenv("GH_TOKEN")
    assert "$GH_TOKEN is empty" in ci_mcp.ci_status("build")
    assert "names no token_env" in ci_mcp.ci_status("notoken")


def test_an_unknown_pipeline_names_the_configured_ones(ci):
    assert "no pipeline 'nope'; configured: build, gl, jenkins, notoken" in ci_mcp.ci_status("nope")


def test_an_http_error_comes_back_as_text(ci, stub):
    assert "-> 404" in ci_mcp.ci_status("build")


def test_no_config_says_what_to_write(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_mcp, "CONFIG", tmp_path / "missing.yaml")
    assert "no pipelines are configured" in ci_mcp.ci_status("build")
