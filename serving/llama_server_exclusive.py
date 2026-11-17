"""Start llama-server for llama-swap with the GPU to itself (one model at a time).

llama-swap runs this instead of llama-server directly:
    python serving\\llama_server_exclusive.py <path\\to\\llama-server.exe> <llama-server args...>
1. Unloads Ariadne's own Ollama models (names starting with ARIADNE_OLLAMA_PREFIX, default "ariadne-") via
   Ollama's keep_alive=0 and waits until they are gone. Never touches other models (Atlas shares Ollama).
2. Windows: starts llama-server inside a job object with KILL_ON_JOB_CLOSE, so when llama-swap stops this
   wrapper on a swap, llama-server dies with it (no orphan holding VRAM). POSIX: exec()s llama-server in place.
Why: A5 measured an Ollama 9B left loaded (5 min keep-alive) next to llama-swap's 9B: 1.8 GB spilled to
shared memory and one model call took 99.8 s instead of ~12 s.
"""
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes

OLLAMA = os.environ.get("ARIADNE_OLLAMA_URL", "http://127.0.0.1:11434")
PREFIX = os.environ.get("ARIADNE_OLLAMA_PREFIX", "ariadne-")


def _ollama(path, body=None, timeout=5):
    req = urllib.request.Request(OLLAMA + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def unload_ariadne_ollama_models(wait_s=15.0):
    try:
        loaded = [m["name"] for m in _ollama("/api/ps").get("models", [])]
    except Exception as exc:  # Ollama not running: nothing to unload
        print(f"[exclusive] ollama not reachable ({exc}); continuing", file=sys.stderr)
        return []
    mine = [n for n in loaded if n.startswith(PREFIX)]
    for name in mine:
        try:
            _ollama("/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
        except Exception as exc:
            print(f"[exclusive] unload {name} failed: {exc}", file=sys.stderr)
    deadline = time.time() + wait_s
    while mine and time.time() < deadline:
        still = [m["name"] for m in _ollama("/api/ps").get("models", []) if m["name"] in mine]
        if not still:
            break
        time.sleep(0.5)
    if mine:
        print(f"[exclusive] unloaded Ollama models: {', '.join(mine)}", file=sys.stderr)
    return mine


class _ExtLimits(ctypes.Structure):
    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                   "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _kill_on_close_job():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    info = _ExtLimits()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # ExtendedLimitInformation
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    return k32, job


def main():
    exe, args = sys.argv[1], sys.argv[2:]
    unload_ariadne_ollama_models()
    if os.name != "nt":  # POSIX: become llama-server, so llama-swap's stop signal reaches it directly
        os.execv(exe, [exe, *args])
    k32, job = _kill_on_close_job()
    proc = subprocess.Popen([exe, *args])
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x0001 | 0x0100, False, proc.pid)  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
    if not h or not k32.AssignProcessToJobObject(job, h):
        proc.kill()
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
    sys.exit(proc.wait())  # if this wrapper is killed, the job handle closes and llama-server dies with it


if __name__ == "__main__":
    main()
