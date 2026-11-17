"""MCP server: give Ariadne a task and see it through brief, backbrief, sign-off, execute (stdio).
Run: python -m ariadne.tasks_mcp

Used by Claude and other MCP clients directly, and by the Hermes gateway (Slack, CLI, Desktop, VS Code chat)
through the ariadne-tasks skill. Calling any tool makes sure the single worker process is running."""
import json

from mcp.server.mcpserver import MCPServer

from .orchestrator import FINAL, WAITING, Store, TaskError, ensure_worker

server = MCPServer(
    "ariadne-tasks",
    instructions=("Ariadne runs work on local models with a military-style drill: you submit a task (brief), "
                  "the worker plans it read-only and returns a backbrief, the person who gave the task signs "
                  "off (approve / revise / cancel), then it executes and reports. Use wait_task to get the "
                  "backbrief and the final report; show the backbrief to the person verbatim and let them decide."))
_store = None


def store():
    global _store
    if _store is None:
        _store = Store()
    return _store


def _view(t):
    keep = ("id", "status", "flow", "session", "source", "text", "workspace", "plan", "models", "result", "error",
            "events")
    v = {k: t.get(k) for k in keep if t.get(k)}
    if t["status"] == "awaiting_signoff":
        v["next"] = ("Show the backbrief (plan, including its MODEL PLAN) to the person. They approve (approve_task, "
                     "optionally changing models), revise (revise_task) or cancel.")
    elif t["status"] == "needs_attention":
        v["next"] = ("The worker stopped (see result): off-plan, a model that would not install, or a missing tool. "
                     "The person fixes it and approves again, revises (revise_task) or cancels.")
    elif t["status"] not in FINAL:
        v["next"] = "Working. Call wait_task again."
    return json.dumps(v, indent=2, default=str)


def _guard(fn):
    try:
        return fn()
    except TaskError as e:
        return json.dumps({"error": str(e)})


@server.tool()
def submit_task(text: str, workspace: str = "", flow: str = "", source: str = "mcp", session: str = "") -> str:
    """Brief: give Ariadne a task. workspace: folder it applies to (e.g. a repo path). flow: optional, else the
    router picks (coding, design, writing, content). session: pass your own conversation id to continue one
    worker conversation across tasks (it remembers earlier tasks in it); default: a new session per task.
    Returns the task id; then call wait_task for the backbrief."""
    def go():
        tid = store().submit(text, source or "mcp", workspace, flow, session)
        ensure_worker()
        return json.dumps({"id": tid, "status": "new", "next": "call wait_task(id) to get the backbrief"})
    return _guard(go)


@server.tool()
def wait_task(id: str, timeout_seconds: int = 50) -> str:
    """Wait until the task needs someone (backbrief ready, off-plan, finished) or the timeout passes.
    Returns the task. If it is still working, call again."""
    def go():
        ensure_worker()
        return _view(store().wait(id, timeout=max(1, min(int(timeout_seconds), 280))))
    return _guard(go)


@server.tool()
def get_task(id: str) -> str:
    """Current state of a task, with its backbrief, result and event log."""
    return _guard(lambda: _view(store().get(id)))


@server.tool()
def approve_task(id: str, models: str = "") -> str:
    """Sign-off: the person approved the backbrief, which locks its model plan. The worker fetches any model that is
    not installed, then executes. models: optional changes first, e.g. "2=gemma-4-12b,3=sd-turbo" or "all=qwen3.5-9b"."""
    def go():
        store().approve(id, models or None)
        ensure_worker()
        return _view(store().get(id))
    return _guard(go)


@server.tool()
def revise_task(id: str, feedback: str) -> str:
    """Sign-off: the person wants changes. The worker re-plans with this feedback and sends a new backbrief."""
    def go():
        store().revise(id, feedback)
        ensure_worker()
        return _view(store().get(id))
    return _guard(go)


@server.tool()
def cancel_task(id: str) -> str:
    """Sign-off: the person cancelled the task."""
    def go():
        store().cancel(id)
        return _view(store().get(id))
    return _guard(go)


@server.tool()
def list_sessions(limit: int = 10) -> str:
    """Ariadne sessions (workstreams): name, tasks given in it, current segment, and the start of its last handoff
    brief. Pass a name as submit_task(session=...) to continue it."""
    return json.dumps(store().sessions(max(1, min(int(limit), 50))), indent=2, default=str)


@server.tool()
def list_tasks(limit: int = 10) -> str:
    """Recent tasks and their status."""
    return json.dumps(store().list(max(1, min(int(limit), 50))), indent=2, default=str)


def main():
    from .deps import require
    require()
    server.run("stdio")


if __name__ == "__main__":
    main()
