"""Host Ariadne for other clients: the ariadne-tasks MCP server over streamable HTTP, behind a bearer token.

    python -m ariadne.host serve [--host 127.0.0.1] [--port 8765]   # MCP endpoint http://<host>:<port>/mcp
    python -m ariadne.host connect [--host <name or IP clients use>] # print client configs with the token
    python -m ariadne.host token [--rotate]                          # show (or replace) the token

Loopback by default. Binding 0.0.0.0 (or a LAN IP) lets other machines connect; the Windows firewall must allow
the port, and every request needs `Authorization: Bearer <token>`. Models stay on loopback: remote clients give
tasks to Ariadne, they do not call the models. The token lives in .ariadne/token (gitignored) unless
ARIADNE_TOKEN is set.
"""
import argparse
import hmac
import json
import os
import secrets
import socket
import sys

from . import paths

TOKEN_FILE = paths.STATE / "token"
DEFAULT_PORT = 8791


def get_token(rotate=False):
    if os.environ.get("ARIADNE_TOKEN") and not rotate:
        return os.environ["ARIADNE_TOKEN"]
    paths.ensure()
    if rotate or not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


class BearerAuth:
    """ASGI middleware: every request except GET /health must carry the bearer token."""

    def __init__(self, app, token):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope.get("path") == "/health" and scope.get("method") == "GET":
            return await _plain(send, 200, b"ok")
        auth = dict(scope.get("headers") or []).get(b"authorization", b"")
        if not (auth.startswith(b"Bearer ") and hmac.compare_digest(auth[7:].strip(), self.token)):
            return await _plain(send, 401, b"missing or wrong bearer token")
        return await self.app(scope, receive, send)


async def _plain(send, status, body):
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def build_app(host, token):
    from mcp.server.transport_security import TransportSecuritySettings

    from .tasks_mcp import server
    # The bearer token is the access control; Host-header checks would refuse LAN clients that use our IP.
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = server.streamable_http_app(host=host, transport_security=security)
    return BearerAuth(app, token)


def serve(host, port):
    import uvicorn

    from .orchestrator import ensure_worker
    token = get_token()
    ensure_worker()
    print(f"Ariadne tasks MCP on http://{host}:{port}/mcp (bearer token in {TOKEN_FILE}); health: /health", flush=True)
    uvicorn.run(build_app(host, token), host=host, port=port, log_level="warning")


def client_configs(host, port, token):
    url = f"http://{host}:{port}/mcp"
    auth = {"Authorization": f"Bearer {token}"}
    return {
        "claude_code": f"claude mcp add --transport http ariadne-tasks {url} --header \"Authorization: Bearer {token}\"",
        "claude_desktop_or_any_mcp_json": {"mcpServers": {"ariadne-tasks": {"type": "http", "url": url, "headers": auth}}},
        "hermes_config_yaml": f"mcp_servers:\n  ariadne_tasks:\n    url: \"{url}\"\n    headers:\n"
                              f"      Authorization: \"Bearer {token}\"\n    timeout: 300\n",
        "local_stdio_no_network": {"mcpServers": {"ariadne-tasks": {
            "command": str(paths.ROOT / ".venv" / "Scripts" / "python.exe"), "args": ["-m", "ariadne.tasks_mcp"],
            "env": {"PYTHONPATH": str(paths.ROOT)}}}},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ariadne-host")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=DEFAULT_PORT)
    c = sub.add_parser("connect"); c.add_argument("--host", default=""); c.add_argument("--port", type=int, default=DEFAULT_PORT)
    t = sub.add_parser("token"); t.add_argument("--rotate", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        serve(a.host, a.port)
    elif a.cmd == "connect":
        cfg = client_configs(a.host or socket.gethostname(), a.port, get_token())
        print("# Claude Code\n" + cfg["claude_code"] + "\n")
        print("# Claude Desktop / any MCP client (HTTP)\n" + json.dumps(cfg["claude_desktop_or_any_mcp_json"], indent=2) + "\n")
        print("# Hermes on another machine (config.yaml)\n" + cfg["hermes_config_yaml"])
        print("# Same machine, no network (stdio)\n" + json.dumps(cfg["local_stdio_no_network"], indent=2))
    elif a.cmd == "token":
        print(get_token(rotate=a.rotate))
    return 0


if __name__ == "__main__":
    sys.exit(main())
