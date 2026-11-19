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


from . import present, service

# The cosmetic layer is `present.py`; nothing here formats a task on its own, so MCP, the chat, the terminal and
# the desktop cannot drift apart.
STATUS = present.STATUS


def card(t, nxt=""):
    return present.text(t, nxt)


def _next(t):
    """Guidance for whoever is calling (a model, usually). Not cosmetics - the card comes from present."""
    s = t["status"]
    if s == "awaiting_gates":
        return "Ask the person for the check gates (how we know it is done, end to end), then call set_gates."
    if s == "awaiting_signoff":
        return ("Show the backbrief to the person. They approve (approve_task, optionally changing models), "
                "revise (revise_task) or cancel.")
    if s == "needs_attention":
        return ("The worker stopped (see result): off-plan, a model that would not install, or a missing tool. "
                "The person fixes it and approves again, revises (revise_task) or cancels.")
    if s not in FINAL:
        return "Working. Call wait_task again."
    return ""


def _view(t):
    nxt = _next(t)
    state = {"id": t["id"], "status": t["status"], "flow": t.get("flow") or "", "session": t.get("session") or "",
             "actions": present.view(t)["actions"], "next": nxt}
    return card(t, nxt) + "\n\n```json\n" + json.dumps(state, indent=1, default=str) + "\n```"


def _guard(fn):
    try:
        return fn()
    except TaskError as e:
        return json.dumps({"error": str(e)})


from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "tasks")

@server.tool()
def submit_task(text: str, flow: str, model: str, gates: list[str] | None = None, workspace: str = "",
                source: str = "mcp", session: str = "") -> str:
    """Brief: give Ariadne a task. `flow` and `model` are REQUIRED and closed sets - call get_choices() for the
    approved flows and agent models; an unnamed or unapproved one is refused, because a task that enters here must
    be one the desktop would accept. workspace: the folder it applies to. session: your conversation id, to continue
    one worker conversation across tasks; default: the workspace folder's name.
    gates: REQUIRED in practice - how we will know it is done, end to end: commands that must pass ("run: pytest -q")
    and outcomes a reviewer checks ("DESIGN.md names one vector store and why"). Ask the person if they did not say;
    without gates the task waits in awaiting_gates. Returns the task card; then call wait_task."""
    def go():
        tid = service.submit(text, source=source or "mcp", workspace=workspace, flow=flow, model=model,
                             session=session, gates=gates)
        ensure_worker()
        # Every task tool returns the same card, so the caller can show the brief (or the gates question) at once.
        return _view(store().get(tid))
    return _guard(go)


DRILL = [
    "1. get_choices - the approved flows and agent models. Both are closed sets; never invent a name.",
    "2. submit_task(text, flow, model, gates, workspace, session) - gates say how we know it is done, end to end.",
    "3. wait_task(id) - the card comes back; call it again while the card says 'Working'.",
    "4. On 'backbrief ready': show the person the card verbatim. They decide - you call approve_task, revise_task "
    "or cancel_task. Never sign off on their behalf.",
    "5. After approval the worker runs on a local model; wait_task again until done, failed, or 'needs you'.",
    "6. get_status answers 'what is happening?' without touching a task; get_task re-reads one card.",
]


@server.tool()
def get_choices() -> str:
    """Read this first: the drill (which tool, in what order) plus the approved flows and agent models a task may
    use. Both lists are closed sets - a name outside them is refused."""
    return _guard(lambda: json.dumps({"drill": DRILL, **service.choices()}, indent=1))


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
def get_status() -> str:
    """What the local model is doing right now: which task holds it, whether one is parked, and which tasks are
    waiting on the person. Use it when they ask "what's happening?" or before deciding to wait on something."""
    from . import park
    return (present.inbox_text(service.inbox()) + "\n\n```json\n"
            + json.dumps(park.status(store()), indent=2, default=str) + "\n```")


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
def set_gates(id: str, gates: list[str]) -> str:
    """Set the check gates of a task that is waiting for them (awaiting_gates), or replace them before execution."""
    def go():
        store().set_gates(id, gates)
        ensure_worker()
        return _view(store().get(id))
    return _guard(go)


@server.tool()
def feedback_task(id: str, feedback: str) -> str:
    """Feedback on a task's plan, work or report, at any time (also after it is done): the person's words plus your
    own review. It stays open until folded into a shared skill with save_skill."""
    def go():
        store().feedback(id, feedback)
        return json.dumps({"id": id, "next": "recorded; fold it into the flow's skills with save_skill"})
    return _guard(go)


@server.tool()
def list_skills(flow: str = "") -> str:
    """The shared skills every run of a flow loads (skills/<flow>/<name>/SKILL.md in the repo), and the feedback
    not yet folded into any skill."""
    from . import skills
    return json.dumps({"skills": skills.list_skills(flow or None), "open_feedback": store().open_feedback()}, indent=2)


@server.tool()
def get_skill(flow: str, name: str) -> str:
    """The full SKILL.md of a shared skill."""
    from . import skills
    try:
        return skills.read(flow, name)
    except skills.SkillError as e:
        return json.dumps({"error": str(e)})


@server.tool()
def save_skill(flow: str, name: str, content: str, note: str = "", resolves: list[str] | None = None) -> str:
    """Create or rewrite a shared skill for a flow from feedback and your review of the work. Write it yourself:
    complete SKILL.md, starting with '---\nname: <name>\ndescription: <when to use it>\n---', then imperative,
    specific guidance for the local worker (what to do, what to avoid, conventions the person wants), under ~500
    words; keep what still holds when rewriting (read it with get_skill first). It is committed and pushed, and loads
    in every later run of the flow. resolves: task ids whose feedback this skill now covers."""
    from . import skills
    try:
        report = skills.save(flow, name, content, note)
    except skills.SkillError as e:
        return json.dumps({"error": str(e)})
    if resolves:
        store().resolve_feedback(resolves)
    return json.dumps({"saved": f"{flow}/{name}", "report": report})


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
