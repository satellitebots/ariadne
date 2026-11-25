"""Jobs: the model writes what should happen, Ariadne runs it with the machine to itself.

A model does not run installs, ingests, builds, evals or full test suites in its own terminal. It writes a script
(or a command) and submits it as a job (jobs_mcp.submit_job), then ends its turn. The worker then
  1. parks the model's KV cache and unloads the agent model from the model server,
  2. runs the job outside any session, with its output in .ariadne/logs/jobs/<id>.log,
  3. resumes the same Hermes session with the result (exit code, duration, log tail, expected outputs, report file
     and the model's own note on what to do next) - the callback.
No timeouts to babysit, no polling, and the model and the heavy work never hold the machine at the same time.
Quick commands (read a file, git status, one test file) stay in the model's terminal.
"""
import json
import os
import sqlite3
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from . import paths

SCHEMA = """CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, task_id TEXT, created REAL, command TEXT, workdir TEXT, why TEXT, after TEXT,
  expects TEXT DEFAULT '[]', report TEXT DEFAULT '', max_minutes INTEGER DEFAULT 240, status TEXT,
  exit_code INTEGER, started REAL, ended REAL, log TEXT DEFAULT '', result TEXT DEFAULT '')"""
MAX_MINUTES = 8 * 60


def _db(db_path=None):
    c = sqlite3.connect(str(db_path or paths.TASKS_DB), timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def submit(task_id, command, workdir, why="", after="", expects=(), report="", max_minutes=240, db_path=None):
    if not command.strip():
        raise ValueError("command is empty")
    jid = "j" + time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    with _db(db_path) as c:
        c.execute("INSERT INTO jobs(id, task_id, created, command, workdir, why, after, expects, report, max_minutes,"
                  " status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (jid, task_id, time.time(), command, str(workdir), why, after, json.dumps(list(expects)), report,
                   max(1, min(int(max_minutes or 240), MAX_MINUTES)), "pending"))
    return jid


def get(jid, db_path=None):
    with _db(db_path) as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    return dict(r) if r else None


def for_task(task_id, status=None, db_path=None):
    q, a = "SELECT * FROM jobs WHERE task_id=?", [task_id]
    if status:
        q, a = q + " AND status=?", a + [status]
    with _db(db_path) as c:
        return [dict(r) for r in c.execute(q + " ORDER BY created", a)]


def _update(jid, db_path=None, **f):
    with _db(db_path) as c:
        c.execute(f"UPDATE jobs SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), jid))


def unload_models(base=None):
    """Free the GPU and RAM for the job: llama-swap's /unload stops every loaded model (the job loads what it uses)."""
    if base is None:
        try:
            from . import serving
            base = serving.base()
        except Exception:
            base = f"http://127.0.0.1:{paths.PORT_MODELS}"
    try:
        urllib.request.urlopen(base.rstrip("/") + "/unload", timeout=60).read()
        return True
    except Exception:
        return False


def _tail(path, lines=80, limit=6000):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])[-limit:]


def _bash():
    """The bash the workers' terminal uses (Git for Windows, as Hermes resolves it); '' when there is none."""
    if os.name != "nt":
        return ""
    try:
        import pm.shell
        b = pm.shell.bash()
        if b:
            return b
    except Exception:
        pass
    for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if Path(p).exists():
            return p
    return ""


def shell_command(command):
    """(args, shell): a job runs in the same shell the worker wrote it for. On Windows that is Git Bash - cmd.exe
    does not understand `cd /c/...` or `.venv/bin/...`, which failed every job of the first real run."""
    bash = _bash()
    return ([bash, "-lc", command], False) if bash else (command, True)


def run(job, db_path=None, unload=unload_models, poll=2.0):
    """Run one job to the end (or its max_minutes). Returns the job row with its result filled in."""
    logs = paths.LOGS / "jobs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{job['id']}.log"
    unload()
    started = time.time()
    _update(job["id"], db_path, status="running", started=started, log=str(log))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with open(log, "w", encoding="utf-8") as out:
        out.write(f"$ {job['command']}\n(cwd {job['workdir']})\n\n")
        out.flush()
        args, use_shell = shell_command(job["command"])
        p = subprocess.Popen(args, shell=use_shell, cwd=job["workdir"] or None, env=env, stdout=out,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags,
                             start_new_session=os.name != "nt")
        status, deadline = "done", started + job["max_minutes"] * 60
        while p.poll() is None:
            if time.time() > deadline:
                from .procs import kill_tree
                kill_tree(p.pid)
                status = "timeout"
                break
            time.sleep(poll)
        code = p.wait()
    if status != "timeout" and code != 0:
        status = "failed"
    ended = time.time()
    expects = json.loads(job.get("expects") or "[]")
    wd = Path(job["workdir"] or ".")
    found = {e: (wd / e).exists() for e in expects}
    report = ""
    if job.get("report"):
        rp = wd / job["report"]
        report = rp.read_text(encoding="utf-8", errors="replace")[:6000] if rp.exists() else "(report file missing)"
    result = {"exit_code": code, "seconds": round(ended - started, 1), "expects": found, "report": report,
              "log_tail": _tail(log)}
    _update(job["id"], db_path, status=status, exit_code=code, ended=ended, result=json.dumps(result))
    return get(job["id"], db_path)


def result_text(job):
    """What the model reads when it is woken: everything it needs to decide the next step."""
    r = json.loads(job.get("result") or "{}")
    lines = [f"JOB {job['id']} {job['status'].upper()}: exit code {r.get('exit_code')} after {r.get('seconds')} s",
             f"command: {job['command']}", f"why: {job['why']}"]
    if r.get("expects"):
        lines.append("expected outputs: " + ", ".join(f"{k} {'present' if v else 'MISSING'}"
                                                      for k, v in r["expects"].items()))
    if job.get("report"):
        lines += [f"report file {job['report']}:", r.get("report") or "(empty)"]
    lines += [f"log ({job['log']}), last lines:", r.get("log_tail") or "(no output)"]
    if job.get("after"):
        lines.append(f"YOUR NOTE FOR WHEN IT FINISHED: {job['after']}")
    return "\n".join(lines)
