"""The HTTP front behind the UI: the verbs, generated from `verbs.VERBS`, a live stream, and the static app.

    python -m ariadne ui            # http://127.0.0.1:8917  (ARIADNE_BIND for a LAN address)

    GET  /api/verbs                 every verb the UI may call: name, group, doc, arguments
    POST /api/v/<verb>              call it with a JSON object of arguments; a person-fixable error is a 400
    GET  /api/stream?since=<ts>     SSE: store events as they happen, plus the machine status every second

Nothing here owns a rule or formats anything: same verbs, same answers as MCP and the chat (docs/DESIGN.md). The
MCP-only bypass verbs are not served here. Loopback by default; `local_only` refuses a public bind.
"""
import json
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import local_only, paths, verbs

UI = Path(__file__).resolve().parent.parent / "ui" / "dist"
DEFAULT_PORT = paths.PORT_UI
VERSION = "2.0"


def verb_list():
    out = []
    for v in verbs.VERBS.values():
        if v.mcp_only:
            continue
        out.append({"name": v.name, "group": v.group, "doc": v.doc, "schema": verbs.schema(v)})
    return out


def stream_batch(since=0.0, limit=200):
    """(text, cursor): SSE frames for every store event after `since`, then one machine frame."""
    rows = verbs.ctx.store.events(since=since, limit=limit)
    text = "".join("event: change\ndata: " + json.dumps(r, default=str) + "\n\n" for r in rows)
    cursor = max([float(r["ts"]) for r in rows], default=float(since or 0))
    m = verbs.call("machine")
    text += "event: machine\ndata: " + json.dumps(m, default=str) + "\n\n"
    return text, cursor


def create_app(ctx=None, start_worker=True):
    """The app; a test passes its own verbs.Ctx so it needs no model and no real database. The mock backend passes
    start_worker=False: its engine runs in-process, and the real daemon must not start."""
    if ctx is not None:
        verbs.ctx = ctx
    app = FastAPI(title="Ariadne", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/health")
    def health():
        from ..daemon import worker_running
        return {"ok": True, "version": VERSION, "worker": worker_running(), "machine": verbs.call("machine")}

    @app.get("/api/verbs")
    def verb_index():
        return verb_list()

    @app.post("/api/v/{name}")
    def call(name: str, args: dict = Body(default={})):
        v = verbs.VERBS.get(name)
        if not v or v.mcp_only:
            raise HTTPException(status_code=404, detail=f"no verb '{name}'")
        try:
            out = verbs.call(name, **(args or {}))
        except verbs.VerbError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if start_worker and name in ("run", "rerun", "sign", "schedule", "resume", "chat", "say"):
            from ..daemon import ensure_worker
            try:
                ensure_worker()
            except Exception:
                pass
        return out

    @app.get("/api/stream")
    def stream(since: float = 0.0):
        def gen():
            cursor = float(since)
            yield "retry: 2000\n\n"
            while True:
                text, cursor = stream_batch(cursor)
                yield text
                time.sleep(1.0)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if (UI / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(UI / "assets")), name="assets")

    @app.get("/")
    def index():
        return FileResponse(str(UI / "index.html"))

    return app


def check_bind(host: str) -> str:
    """The screen is for this machine or this network. A public bind is refused, like a public model."""
    if host in ("localhost", "::1") or local_only.is_lan_host(host):
        return host
    raise SystemExit(f"refusing to bind the UI to {host}: it is not this machine or the LAN. Use 127.0.0.1 "
                     f"(or ARIADNE_BIND for a LAN address).")


def main(argv=None):
    import os
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    port = int(os.environ.get("ARIADNE_PORT") or DEFAULT_PORT)
    bind = os.environ.get("ARIADNE_BIND") or "127.0.0.1"
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--bind" in argv:
        bind = argv[argv.index("--bind") + 1]
    check_bind(bind)
    import uvicorn
    print(f"Ariadne: http://{bind}:{port}")
    uvicorn.run(create_app(), host=bind, port=port, log_level="warning", timeout_graceful_shutdown=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
