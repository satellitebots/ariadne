"""Background processes that outlive whoever started them.

The worker and the model server must not die with the terminal, chat, desktop app or remote session that happened
to start them. On Windows a process belongs to its parent's job object, and closing that job (a terminal window,
an MCP bridge, a remote session dropping) kills everything in it. So they are started outside it:
  1. CreateProcess with CREATE_BREAKAWAY_FROM_JOB, when the parent's job allows breakaway;
  2. otherwise through WMI (Win32_Process.Create): the process is created by the WMI service, in no job of ours.
On Linux and macOS a new session (setsid) is enough.

They stop only when asked: `python -m ariadne stop`, or S in the watch window."""
import os
import subprocess
from pathlib import Path

CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def _cmdline(args):
    return subprocess.list2cmdline([str(a) for a in args])


def spawn_detached(args, log: Path, cwd: Path, env_extra: dict | None = None) -> int:
    """Start `args` in the background, appending its output to `log`. Returns a pid (on Windows via WMI: the pid of
    the cmd.exe wrapper, whose tree includes the process)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, **(env_extra or {}))
    if os.name != "nt":
        with open(log, "a", encoding="utf-8") as out:
            p = subprocess.Popen([str(a) for a in args], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out,
                                 stderr=out, start_new_session=True, close_fds=True)
        return p.pid
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
             | CREATE_BREAKAWAY_FROM_JOB)
    try:
        with open(log, "a", encoding="utf-8") as out:
            p = subprocess.Popen([str(a) for a in args], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out,
                                 stderr=out, creationflags=flags, close_fds=True)
        return p.pid
    except OSError:
        pass  # the parent's job does not allow breakaway: start it through WMI instead
    # A WMI-created process starts with the system environment, so the variables it needs are set by the cmd wrapper.
    sets = "".join(f"set {k}={v}&& " for k, v in (env_extra or {}).items())
    cmd = f'cmd /c "{sets}{_cmdline(args)} >> "{log}" 2>&1"'
    ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
          "@{CommandLine = $env:ARIADNE_SPAWN_CMD; CurrentDirectory = $env:ARIADNE_SPAWN_CWD}; "
          "if ($r.ReturnValue -ne 0) { exit 1 }; $r.ProcessId")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, ARIADNE_SPAWN_CMD=cmd, ARIADNE_SPAWN_CWD=str(cwd)))
    if r.returncode != 0 or not r.stdout.strip().isdigit():
        raise OSError(f"could not start {args[0]} outside this session: {r.stderr.strip()[:300]}")
    return int(r.stdout.strip())


def kill_tree(pid: int):
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
