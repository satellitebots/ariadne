"""Background processes that outlive whoever started them.

The worker and the model server must not die with the terminal, chat, desktop app or remote session that happened
to start them. On Windows a process belongs to its parent's job object, and closing that job (a terminal window,
an MCP bridge, a remote session dropping) kills everything in it. So they are started outside it:
  1. CreateProcess with CREATE_BREAKAWAY_FROM_JOB, when the parent's job allows breakaway;
  2. otherwise through WMI (Win32_Process.Create): the process is created by the WMI service, in no job of ours.
On Linux and macOS a new session (setsid) is enough.

They stop only when asked: `python -m ariadne stop`, or S in the watch window."""
import ctypes
import os
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path

CREATE_BREAKAWAY_FROM_JOB = 0x01000000
JOB_NAME = "Local\\ariadne"          # one named group: every process Ariadne starts belongs to it
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001

_job_lock = threading.Lock()
_job_handle = None


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_ulonglong), ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong), ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong), ("OtherTransferCount", ctypes.c_ulonglong)]


class _BASIC_LIMIT(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _job():
    """The named job object, created on first use. A named job is visible to every Ariadne process, so any of them
    can adopt into it and `stop` can kill the whole group even if the process that started it is gone."""
    global _job_handle
    if os.name != "nt":
        return None
    with _job_lock:
        if _job_handle:
            return _job_handle
        k = ctypes.windll.kernel32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        h = k.CreateJobObjectW(None, JOB_NAME)
        if not h:
            return None
        info = _EXTENDED_LIMIT()
        # No KILL_ON_JOB_CLOSE: the group must survive the shell that launched it. `stop` terminates it explicitly.
        info.BasicLimitInformation.LimitFlags = 0
        k.SetInformationJobObject(h, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info))
        _job_handle = h
        return h


def join():
    """Put this process (and so everything it spawns) in the Ariadne job. Best effort: a process already inside a
    job that forbids nesting still has its children adopted individually."""
    h = _job()
    if not h:
        return False
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wintypes.HANDLE
    try:
        return bool(k.AssignProcessToJobObject(h, k.GetCurrentProcess()))
    except OSError:
        return False


def adopt(pid):
    """Put an already-started process in the job; its own children inherit membership."""
    h = _job()
    if not h or not pid:
        return False
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    ph = k.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
    if not ph:
        return False
    try:
        return bool(k.AssignProcessToJobObject(h, ph))
    finally:
        k.CloseHandle(ph)


def terminate_job():
    """The kill switch: terminate every process in the Ariadne job, including ones whose parent is long gone."""
    h = _job()
    if not h:
        return False
    try:
        return bool(ctypes.windll.kernel32.TerminateJobObject(h, 1))
    except OSError:
        return False


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
        adopt(p.pid)
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
    pid = int(r.stdout.strip())
    adopt(pid)
    return pid


def kill_on_ports(ports):
    """Hard closeout: force-kill whatever is listening on the given ports, whatever started it.

    The job object only reaches what joined the group. Anything spawned through another path (a hand-started
    uvicorn, an orphaned browser debug port, a model server no pid file knows) dies here by what it holds open."""
    killed = []
    if os.name == "nt":
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "LISTEN" not in line:
                continue
            for port in ports:
                if f":{port}" in line:
                    pid = line.split()[-1]
                    if pid.isdigit():
                        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                        killed.append(pid)
    else:
        import signal
        for port in ports:
            r = subprocess.run(["sh", "-c", f"lsof -t -i:{port} 2>/dev/null || true"],
                               capture_output=True, text=True)
            for pid in r.stdout.split():
                if pid.strip().isdigit():
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                        killed.append(pid)
                    except OSError:
                        pass
    return sorted(set(killed))


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
