"""MCP server: jobs - hand heavy work to Ariadne instead of running it yourself (stdio).
Run: python -m ariadne.jobs_mcp   (the flow sets ARIADNE_FLOW_HOME; the worker writes the current task there)."""
import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import jobs

server = MCPServer("ariadne-jobs", instructions=(
    "For anything heavy or long - installs, ingest, embedding, builds, evals, full test suites, downloads - do not "
    "run it in the terminal. Write the script into the workspace, call submit_job, then END YOUR TURN by replying "
    "'JOB SUBMITTED: <id>' and nothing else. Ariadne unloads you, runs the job with the whole machine, and wakes you "
    "in this same conversation with the result. Quick commands (read, grep, git status, one test file) stay in the "
    "terminal."))

from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "jobs")


def _here():
    home = Path(os.environ.get("ARIADNE_FLOW_HOME", "."))
    read = lambda n: (home / n).read_text(encoding="utf-8").strip() if (home / n).exists() else ""
    return read("ariadne_task"), read("ariadne_workspace")


@server.tool()
def submit_job(command: str, why: str, after: str = "", expects: list[str] | None = None, report: str = "",
               max_minutes: int = 240, workdir: str = "") -> str:
    """Queue heavy work for Ariadne to run once you end your turn.
    command: the shell command, usually `python scripts/ingest.py --resume` - a script you wrote in the workspace.
    why: one line, what it does. after: your note for when it finishes (what to check, what to do next).
    expects: files it should produce (relative to the workspace). report: a file it writes with its real numbers
    (e.g. ingest_report.json); you get its content back. max_minutes: hard stop (default 240).
    After calling this, reply 'JOB SUBMITTED: <id>' and stop."""
    task, workspace = _here()
    if not task:
        return "no Ariadne task is running here; run the command in the terminal instead"
    jid = jobs.submit(task, command, workdir or workspace, why, after, expects or [], report, max_minutes)
    return (f"job {jid} queued. Now end your turn: reply exactly 'JOB SUBMITTED: {jid}'. You will be woken in this "
            "conversation with its result.")


@server.tool()
def need_login(site: str, why: str) -> str:
    """A step needs you signed in to a site (or a one-time code, a CAPTCHA, a payment). Never type credentials
    yourself. Ariadne pauses this task after this call and asks the person to sign in in their own Chrome; you are
    resumed here afterwards. site: the site or app (e.g. github.com). why: what you need the login for."""
    from . import browser, park
    task, _ = _here()
    note = browser.login_note(site, why)
    park.request(by=note)
    if task:
        from .durable import Store
        Store().event(task, "login", note)
    return ("Paused for the person to sign in. Reply 'LOGIN NEEDED: " + site + "' and stop. When you are resumed, "
            "check in the browser that you are signed in before going on; if not, call need_login again.")


@server.tool()
def list_jobs() -> str:
    """This task's jobs: status, exit code, how long they took."""
    task, _ = _here()
    rows = jobs.for_task(task) if task else []
    return json.dumps([{k: j[k] for k in ("id", "status", "exit_code", "why", "command")} for j in rows], indent=2)


@server.tool()
def job_result(id: str) -> str:
    """The full result of a finished job (the same text you were woken with)."""
    j = jobs.get(id)
    if not j:
        return f"no job {id}"
    return jobs.result_text(j) if j["status"] not in ("pending", "running") else f"job {id} is {j['status']}"


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
