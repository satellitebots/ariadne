"""Ariadne's own server: the verbs from `service.py`, the views from `present.py`, SSE, and the static UI.

    python -m ariadne ui            # http://127.0.0.1:8787  (ARIADNE_BIND for a LAN interface)

Nothing here owns a rule or formats a task. Routes call `service`; the document comes from `present.view()`; the page
reads it and renders. That is what keeps the terminal, MCP and the browser showing the same task (docs/FRONTEND.md).

Loopback by default: `local_only` checks the bind, so the screen is for this machine or this network, never the
internet. No bundler, no Node: one static ES module, served by the same process.
"""
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import local_only, paths, present, service
from ..errors import TaskError

UI = Path(__file__).resolve().parent.parent / "ui"
DEFAULT_PORT = 8787
VERSION = "1.0"


class SubmitIn(BaseModel):
    text: str
    flow: str = ""
    model: str = ""
    workspace: str = ""
    session: str = ""
    gates: list[str] = []


class ModelsIn(BaseModel):
    models: str = ""


class ReviseIn(BaseModel):
    feedback: str


class GatesIn(BaseModel):
    gates: list[str]


class ChatIn(BaseModel):
    message: str
    session: str = ""


def _call(fn, *a, **kw):
    """A rulebook refusal is a 400 with the same sentence the terminal and MCP show, never a traceback."""
    try:
        return fn(*a, **kw)
    except TaskError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


def _doc(t, store):
    """The task as a surface reads it: `present.view` plus its Markdown card and the verbs legal right now."""
    v = present.view(t, _next(t))
    return {**v, "card": present.text(t, _next(t))}


def _next(t):
    s = t.get("status")
    if s == "awaiting_gates":
        return "Set the check gates: how we know it is done, end to end."
    if s == "awaiting_signoff":
        return "Read the backbrief, then approve, revise or cancel."
    if s == "needs_attention":
        return "It stopped and needs you: approve to continue, revise, or cancel."
    if s in ("done", "failed", "cancelled", "rejected", "timed_out"):
        return ""
    return "Working."


def event_batch(since=0.0, store=None, limit=200):
    """(text, cursor): one SSE frame per event newer than `since`. Split out so it can be tested without a stream."""
    rows = service.events_since(since, limit, store=store)
    text = "".join("data: " + json.dumps(r, default=str) + "\n\n" for r in rows)
    cursor = max([float(r["ts"]) for r in rows], default=float(since or 0))
    return text, cursor


def create_app(store=None, chat_runner=None):
    """The app, with an injectable store and chat runner so a test needs no server, no model and no real database."""
    app = FastAPI(title="Ariadne", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)

    def db():
        return store or service.store()

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": VERSION, "worker": service.inbox(store=db())["worker"]}

    @app.get("/api/choices")
    def choices():
        return _call(service.choices)

    @app.get("/api/inbox")
    def inbox():
        state = service.inbox(store=db())
        return {"waiting": [_doc(t, db()) for t in state["waiting"]],
                "running": [{"id": t["id"], "status": t["status"], "label": present.STATUS.get(t["status"], ""),
                             "text": (t.get("text") or "").splitlines()[:1]} for t in state["running"]],
                "stale": [t["id"] for t in state["stale"]],
                "recent": [{"id": t["id"], "status": t["status"], "label": present.STATUS.get(t["status"], "")}
                           for t in state["recent"]],
                "worker": state["worker"], "text": present.inbox_text(state)}

    @app.get("/api/sessions")
    def sessions(limit: int = 25):
        return _call(service.sessions_view, max(1, min(int(limit), 100)), store=db())

    @app.get("/api/sessions/{name}")
    def session(name: str):
        for s in service.sessions_view(100, store=db()):
            if s["name"] == name:
                return s
        raise HTTPException(status_code=404, detail=f"no session {name}")

    @app.post("/api/tasks")
    def submit(body: SubmitIn):
        tid = _call(service.submit, body.text, source="ui", workspace=body.workspace, flow=body.flow,
                    model=body.model, session=body.session, gates=body.gates or None, store=db())
        return _doc(_call(service.task, tid, store=db()), db())

    @app.get("/api/tasks/{tid}")
    def task(tid: str):
        return _doc(_call(service.task, tid, store=db()), db())

    @app.post("/api/tasks/{tid}/approve")
    def approve(tid: str, body: ModelsIn | None = None):
        return _doc(_call(service.approve, tid, (body.models if body else "") or None, store=db()), db())

    @app.post("/api/tasks/{tid}/revise")
    def revise(tid: str, body: ReviseIn):
        return _doc(_call(service.revise, tid, body.feedback, store=db()), db())

    @app.post("/api/tasks/{tid}/gates")
    def gates(tid: str, body: GatesIn):
        return _doc(_call(service.set_gates, tid, body.gates, store=db()), db())

    @app.post("/api/tasks/{tid}/cancel")
    def cancel(tid: str):
        return _doc(_call(service.cancel, tid, store=db()), db())

    @app.post("/api/tasks/{tid}/feedback")
    def feedback(tid: str, body: ReviseIn):
        return _call(service.feedback, tid, body.feedback, store=db())

    @app.post("/api/chat")
    def chat_turn(body: ChatIn):
        """One turn of the session's conversation. It can submit tasks; it cannot do them (see docs/FRONTEND.md)."""
        from .. import chat
        try:
            return {"reply": chat.ask(body.message, body.session, store=db(), runner=chat_runner),
                    "session": body.session}
        except (chat.ChatError, TaskError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/events")
    def events(since: float = 0.0):
        """SSE: every task event after `since`, then live ones. The client reconnects with its last ts."""
        def stream():
            cursor = float(since)
            yield "retry: 2000\n\n"
            while True:
                text, cursor = event_batch(cursor, db())
                if text:
                    yield text
                else:
                    yield ": keepalive\n\n"
                time.sleep(1.0)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    app.mount("/static", StaticFiles(directory=str(UI)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(UI / "index.html"))

    return app


app = create_app()   # uvicorn ariadne.server.app:app


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
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is missing: rerun `python -m ariadne install` (it comes with the Hermes environment)")
        return 1
    print(f"Ariadne UI: http://{bind}:{port}   (the terminal and MCP stay open; no model is needed to read or sign off)")
    # A browser tab holds the SSE connection open; without a graceful timeout Ctrl+C would wait for it.
    uvicorn.run(create_app(), host=bind, port=port, log_level="warning", timeout_graceful_shutdown=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
