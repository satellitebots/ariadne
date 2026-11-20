"""Our own chat: a conversation bound to one session that can talk, look things up, and submit - never work.

The rule (docs/DESIGN-RESET.md) is enforced by construction, not by a hook: the turn runs on Ariadne's own runtime with
`native_tools=False`, so the file, patch, search-in-files and terminal tools do not exist in the conversation at all.
What it does have is the Ariadne task server (submit_task, list_tasks, get_choices) and read-only web search. The
retired `ariadne_gate` hook refused tools after the model had already chosen them; not offering them is the mechanism.

Two doors share it: `ariadne chat` (a terminal loop) and the console's chat panel, which posts one message at a time to
`/api/chat`. The turn runner is injectable, so every test runs without a model.
"""
import sys

from . import paths, service

HOME_NAME = "chat"


class ChatError(RuntimeError):
    pass


TURN = """This is the conversation attached to Ariadne session "{session}". Ariadne is a local task harness: a brief
becomes a backbrief, a person signs it off, a worker executes it on a local model, and check gates decide.
{context}
The person says:
{message}

Rules for this conversation:
- You may talk, look things up (read-only), and give Ariadne a task with submit_task; the person signs off on it.
- You cannot do the work yourself: you have no files, terminal, code or browser. Never paste work as if you had done
  it, and never suggest signing in to some other service.
- When the person wants work done, agree the brief and the check gates (how we know it is done), then call
  submit_task with a flow and a model from get_choices.
- Answer about this session from the task store; say plainly when you do not know.
"""

CHAT_SYSTEM = """You are Ariadne's chat: a conversation bound to one session of a local task harness. You may talk,
search the web (read-only) and use the Ariadne task tools to submit or inspect tasks. You cannot do the work: this
conversation has no file, patch, search-in-files or terminal tools. Never describe work as done, and never suggest
signing in to another service."""


def chat_model() -> str:
    """The agent model the chat talks with: the first installed one in the approved catalog."""
    from . import models as modellib
    try:
        cat = modellib.load()
    except modellib.ModelError as e:
        raise ChatError(str(e))
    for m in cat.models.values():
        if m.kind == "agent" and m.installed():
            return m.name
    raise ChatError("no approved agent model is installed; fetch one (`ariadne models install <name>`) or ask the "
                    "person to pick another")


def chat_home():
    """The chat's home: its sessions and logs. There is no generated config - the runtime reads the catalog itself."""
    home = paths.HOMES / HOME_NAME
    home.mkdir(parents=True, exist_ok=True)
    return home


def tasks_server():
    """The one MCP server the chat gets: Ariadne's task verbs, over stdio."""
    return {"ariadne_tasks": {"command": str(paths.VENV_PY if paths.VENV_PY.exists() else paths.PYTHON),
                              "args": ["-m", "ariadne.tasks_mcp"],
                              "env": {"PYTHONPATH": str(paths.ROOT)}, "timeout": 120}}


def session_context(session: str, store=None) -> str:
    """What the chat knows about the session without touching a file: its tasks and their states, newest first."""
    if not session:
        return "No session is selected: answer about Ariadne itself, and ask which session they mean before submitting."
    rows = [t for t in service.tasks(60, store=store) if (t.get("session") or "") == session]
    if not rows:
        return f'Session "{session}" has no tasks yet.'
    lines = [f'Session "{session}" - its most recent tasks:']
    for t in rows[:20]:
        lines.append(f"- {t['id']}  {t['status']:<16} {t.get('flow') or '-':<8} {(t.get('text') or '').splitlines()[0][:90]}")
    return "\n".join(lines)


def run_turn(home, prompt, session="", model=""):
    """One turn on the own runtime: the task server and read-only search, and no native tools at all."""
    from . import runtime
    from .runtime.mcp import Pool
    from .runtime.web import Search
    from .worker import RunResult
    pool = Pool(tasks_server())
    try:
        r = runtime.run(prompt, home=home, workspace=str(home), phase="chat", model=model or chat_model(),
                        session=session or "default", max_turns=12, budget=600, mcp=pool, web=Search(),
                        native_tools=False, system=CHAT_SYSTEM)
    finally:
        pool.close()
    return RunResult(r.text, 0 if r.stopped in ("", "budget", "max_turns") else 1, "", session)


def ask(message: str, session: str = "", store=None, runner=None, model: str = "") -> str:
    """One turn of the conversation. Raises ChatError (the caller turns it into a 400), never returns a traceback."""
    message = (message or "").strip()
    if not message:
        raise ChatError("say something first: the chat has nothing to answer")
    home = chat_home()
    prompt = TURN.format(session=session or "(none)", context=session_context(session, store), message=message)
    r = (runner or run_turn)(home, prompt, session, model)
    if getattr(r, "exit_code", 0) != 0 or not (getattr(r, "text", "") or "").strip():
        raise ChatError(f"the chat model did not answer (exit {getattr(r, 'exit_code', '?')}); the models may be down")
    return r.text


def main(argv=None):
    """`ariadne chat [--session NAME]`: the terminal door onto the same rule."""
    argv = list(sys.argv[1:] if argv is None else argv)
    session = ""
    if "--session" in argv:
        i = argv.index("--session")
        session = argv[i + 1] if i + 1 < len(argv) else ""
    print(f"chat{f' (session {session})' if session else ''}: it can submit tasks, not do them. Ctrl+C to leave.")
    while True:
        try:
            line = input("you> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line.strip():
            continue
        try:
            print("ariadne> " + ask(line, session=session))
        except ChatError as e:
            print(f"ariadne> {e}")
