"""MCP server: ci - trigger, watch and read the logs of a pipeline on Jenkins, GitHub Actions or GitLab (stdio).

Run: python -m ariadne.ci_mcp

Pipelines are named in `.ariadne/ci.yaml` (this machine's state, gitignored). A token is never written there: the
entry names the environment variable that holds it, so the file can be copied and the secret stays in the shell.

    pipelines:
      build:
        provider: github          # github | gitlab | jenkins
        repo: my-org/my-repo      # gitlab: group/project; jenkins: folder/job
        workflow: ci.yml          # github only: the workflow file or id
        ref: main                 # default branch/ref for a trigger
        token_env: GH_TOKEN       # the variable holding the token (jenkins also: user_env)

Nothing here calls a model; nothing here is reachable from a task unless the flow lists `ci`.
"""
import base64
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from mcp.server.mcpserver import MCPServer

from . import paths
from . import yamlio as yaml

server = MCPServer("ariadne-ci", instructions=(
    "Trigger a pipeline, see whether the last runs passed, and read the log of a failing one. Pipelines are named "
    "in .ariadne/ci.yaml; call ci_pipelines first to see the names. Logs are trimmed to the tail: ask for more only "
    "when the failing line is not there."))

CONFIG = paths.STATE / "ci.yaml"
DEFAULT_API = {"github": "https://api.github.com", "gitlab": "https://gitlab.com/api/v4"}


class CIError(RuntimeError):
    pass


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect (GitHub sends logs to a signed URL) without carrying our token to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            same = urllib.parse.urlsplit(newurl).netloc == urllib.parse.urlsplit(req.full_url).netloc
            if not same:
                for k in list(new.headers):
                    if k.lower() == "authorization":
                        del new.headers[k]
                new.unredirected_hdrs.pop("Authorization", None)
        return new


_opener = urllib.request.build_opener(_NoAuthRedirect)


def pipelines() -> dict:
    try:
        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    except Exception as e:
        raise CIError(f"{CONFIG} cannot be read: {e}")
    return data.get("pipelines") or {}


def pipeline(name: str) -> dict:
    all_ = pipelines()
    if not all_:
        raise CIError(f"no pipelines are configured: write {CONFIG} with a `pipelines:` map "
                      f"(provider, repo/project/job, token_env)")
    if name not in all_:
        raise CIError(f"no pipeline '{name}'; configured: {', '.join(sorted(all_))}")
    cfg = dict(all_[name])
    if not cfg.get("provider"):
        raise CIError(f"pipeline '{name}' names no provider (github, gitlab or jenkins)")
    return cfg


def _token(cfg, name):
    var = cfg.get("token_env") or ""
    if not var:
        raise CIError(f"pipeline '{name}' names no token_env; the variable that holds the token must be named there")
    val = os.environ.get(var, "")
    if not val:
        raise CIError(f"${var} is empty: export it in the shell that starts the worker (the token is never stored "
                      f"in ci.yaml)")
    return val


def _request(url, headers=None, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Accept": "application/json", "User-Agent": "ariadne-ci", **(headers or {})}
    if body is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:1500]
        raise CIError(f"{method} {url} -> {e.code}: {text or e.reason}")
    except (urllib.error.URLError, OSError) as e:
        raise CIError(f"{method} {url} failed: {e}")


def _json_reply(url, headers=None, method="GET", body=None, timeout=60):
    code, raw, _ = _request(url, headers, method, body, timeout)
    try:
        return json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise CIError(f"{url} answered {code} with something that is not JSON: {raw[:200]!r}")


def _api(cfg, provider):
    return (cfg.get("api") or DEFAULT_API[provider]).rstrip("/")


# ---------- providers ----------

def _github(name, cfg, action, **kw):
    api = _api(cfg, "github")
    repo = cfg.get("repo") or ""
    if not repo:
        raise CIError(f"pipeline '{name}' names no repo (owner/name)")
    auth = {"Authorization": f"Bearer {_token(cfg, name)}"}
    if action == "status":
        q = f"?per_page={int(kw.get('limit') or 5)}"
        if cfg.get("ref"):
            q += "&branch=" + urllib.parse.quote(cfg["ref"])
        runs = _json_reply(f"{api}/repos/{repo}/actions/runs{q}", auth).get("workflow_runs") or []
        return [{"run": r.get("run_number"), "id": r.get("id"), "branch": r.get("head_branch"),
                 "event": r.get("event"), "status": r.get("status"), "conclusion": r.get("conclusion"),
                 "url": r.get("html_url")} for r in runs]
    if action == "trigger":
        wf = cfg.get("workflow") or ""
        if not wf:
            raise CIError(f"pipeline '{name}' names no workflow (the .yml file or its id) to trigger")
        ref = kw.get("ref") or cfg.get("ref") or "main"
        _request(f"{api}/repos/{repo}/actions/workflows/{urllib.parse.quote(wf)}/dispatches", auth, "POST",
                 {"ref": ref})
        return {"triggered": f"{repo}/{wf} on {ref}", "note": "GitHub returns no run id; ci_status shows it shortly"}
    if action == "logs":
        run = str(kw.get("run") or "").strip()
        if not run:
            runs = _json_reply(f"{api}/repos/{repo}/actions/runs?per_page=1", auth).get("workflow_runs") or []
            if not runs:
                raise CIError(f"{repo} has no runs")
            run = runs[0]["id"]
        code, raw, headers = _request(f"{api}/repos/{repo}/actions/runs/{run}/logs", auth)
        if (headers.get("Content-Type") or "").startswith("application/zip") or raw[:2] == b"PK":
            return _unzip_logs(raw)
        return raw.decode("utf-8", "replace")
    raise CIError(f"github does not support '{action}'")


def _unzip_logs(raw: bytes) -> str:
    out = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            out.append(f"--- {name} ---")
            out.append(z.read(name).decode("utf-8", "replace"))
    return "\n".join(out)


def _gitlab(name, cfg, action, **kw):
    api = _api(cfg, "gitlab")
    project = urllib.parse.quote(str(cfg.get("project") or ""), safe="")
    if not project:
        raise CIError(f"pipeline '{name}' names no project (group/project)")
    auth = {"PRIVATE-TOKEN": _token(cfg, name)}
    if action == "status":
        rows = _json_reply(f"{api}/projects/{project}/pipelines?per_page={int(kw.get('limit') or 5)}", auth)
        return [{"run": r.get("iid") or r.get("id"), "id": r.get("id"), "branch": r.get("ref"),
                 "status": r.get("status"), "url": r.get("web_url"), "created": r.get("created_at")} for r in rows]
    if action == "trigger":
        ref = kw.get("ref") or cfg.get("ref") or "main"
        out = _json_reply(f"{api}/projects/{project}/pipeline", auth, "POST", {"ref": ref})
        return {"triggered": f"{project} on {ref}", "run": out.get("iid") or out.get("id"),
                "url": out.get("web_url") or out.get("status")}
    if action == "logs":
        jobs = _json_reply(f"{api}/projects/{project}/jobs?per_page=100", auth)
        run = str(kw.get("run") or "").strip()
        if run:
            jobs = [j for j in jobs if str(j.get("pipeline", {}).get("id")) == run]
        failed = [j for j in jobs if j.get("status") == "failed"] or jobs
        if not failed:
            raise CIError(f"{project} has no job logs yet")
        job = failed[-1]
        code, raw, _ = _request(f"{api}/projects/{project}/jobs/{job['id']}/trace", auth)
        return f"job {job.get('name')} ({job.get('status')}):\n" + raw.decode("utf-8", "replace")
    raise CIError(f"gitlab does not support '{action}'")


def _jenkins(name, cfg, action, **kw):
    base = (cfg.get("url") or "").rstrip("/")
    job = str(cfg.get("repo") or "").strip("/")
    if not base or not job:
        raise CIError(f"pipeline '{name}' needs a url and a job path (folder/job)")
    user = os.environ.get(cfg.get("user_env") or "", "")
    password = _token(cfg, name).strip()
    raw = f"{user}:{password}".encode()
    auth = {"Authorization": "Basic " + base64.b64encode(raw).decode()}
    path = "/".join("job/" + urllib.parse.quote(p, safe="") for p in job.split("/") if p)
    if action == "status":
        out = _json_reply(f"{base}/{path}/api/json?tree=builds[number,result,timestamp,url,duration,builtOn]",
                          auth, timeout=90)
        return [{"run": b.get("number"), "result": b.get("result") or "running", "url": b.get("url"),
                 "duration_ms": b.get("duration"), "built_on": b.get("builtOn")}
                for b in (out.get("builds") or [])[:int(kw.get("limit") or 5)]]
    if action == "trigger":
        params = kw.get("params") or {}
        if params:
            body = urllib.parse.urlencode({k: v for k, v in params.items()}).encode()
            req = urllib.request.Request(f"{base}/{path}/buildWithParameters", data=body,
                                         headers={**auth, "Content-Type": "application/x-www-form-urlencoded"},
                                         method="POST")
            try:
                with _opener.open(req, timeout=60) as r:
                    return {"triggered": job, "status": r.status}
            except urllib.error.HTTPError as e:
                raise CIError(f"jenkins buildWithParameters -> {e.code}: {e.read()[:500]}")
            except (urllib.error.URLError, OSError) as e:
                raise CIError(f"jenkins trigger failed: {e}")
        code, _, _ = _request(f"{base}/{path}/build", auth, "POST")
        return {"triggered": job, "status": code}
    if action == "logs":
        run = str(kw.get("run") or "").strip() or "lastBuild"
        code, body, _ = _request(f"{base}/{path}/{urllib.parse.quote(run)}/consoleText", auth, timeout=90)
        return body.decode("utf-8", "replace")
    raise CIError(f"jenkins does not support '{action}'")


PROVIDERS = {"github": _github, "gitlab": _gitlab, "jenkins": _jenkins}


def _call(action, name, **kw):
    cfg = pipeline(name)
    provider = cfg.get("provider")
    if provider not in PROVIDERS:
        raise CIError(f"unknown provider '{provider}'; use one of {', '.join(PROVIDERS)}")
    return PROVIDERS[provider](name, cfg, action, **kw)


def _tail(text: str, lines: int) -> str:
    rows = (text or "").splitlines()
    return "\n".join(rows[-max(1, min(int(lines), 2000)):])


# ---------- tools ----------

@server.tool()
def ci_pipelines() -> str:
    """The pipelines this machine can drive (from .ariadne/ci.yaml): name, provider, target, whether the token
    variable is set. Call this first."""
    try:
        out = []
        for name, cfg in sorted(pipelines().items()):
            var = cfg.get("token_env") or ""
            out.append({"name": name, "provider": cfg.get("provider") or "",
                        "target": cfg.get("repo") or cfg.get("project") or cfg.get("url") or "",
                        "token": f"${var} {'set' if os.environ.get(var) else 'NOT set'}" if var else "(none named)"})
        return json.dumps(out or "no pipelines configured: write .ariadne/ci.yaml", indent=1)
    except CIError as e:
        return str(e)


@server.tool()
def ci_status(name: str, limit: int = 5) -> str:
    """The last `limit` runs of a pipeline: run number, branch, status/conclusion, url."""
    try:
        return json.dumps(_call("status", name, limit=limit), indent=1)
    except CIError as e:
        return str(e)


@server.tool()
def ci_trigger(name: str, ref: str = "", params: dict | None = None) -> str:
    """Start a run of the pipeline, on `ref` (default: the pipeline's ref) and with `params` (Jenkins parameters)."""
    try:
        return json.dumps(_call("trigger", name, ref=ref, params=params or {}), indent=1)
    except CIError as e:
        return str(e)


@server.tool()
def ci_logs(name: str, run: str = "", lines: int = 200) -> str:
    """The log of a run (default: the newest) trimmed to its last `lines` lines. Ask for more only when the failing
    line is not in the tail."""
    try:
        return _tail(_call("logs", name, run=run), lines)
    except CIError as e:
        return str(e)


from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "ci")


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
