"""Babysit the machine, not the model.

One model holds the GPU at a time, so the failure that matters is the box going down while it does. This is a
script, never a model - a model is the thing that can hang. It samples free RAM, free VRAM and the server's health
on an interval and escalates on fixed thresholds:

    ok -> warn (log) -> unload the model -> kill the server -> flag the task `needs_attention`

Every sample and every action is appended to `.ariadne/logs/watchdog.jsonl`, so a crash afterwards is explainable
in numbers rather than guessed at. The escalation callbacks are injected, which keeps this testable and keeps the
kill path owned by exactly one caller.
"""
import ctypes
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from . import paths

THRESHOLDS = {
    "free_ram_mb": 1500,     # below this the OS starts killing things on its own
    "free_vram_mb": 400,     # below this a load can fail or fall off the card
    "health_s": 8.0,         # a server that takes this long to answer is wedged
    "consecutive": 3,        # samples in a row before escalating: no action on one blip
}
INTERVAL = 5.0
LOG = paths.LOGS / "watchdog.jsonl"
LEVELS = ("ok", "warn", "unload", "kill", "flag")


def _ram():
    """(total_mb, free_mb) without psutil."""
    try:
        if os.name == "nt":
            class _STAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            s = _STAT()
            s.dwLength = ctypes.sizeof(_STAT)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
                return s.ullTotalPhys // 2**20, s.ullAvailPhys // 2**20
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            vals = {}
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                k, _, rest = line.partition(":")
                vals[k.strip()] = int(rest.strip().split()[0]) // 1024
            return vals.get("MemTotal", 0), vals.get("MemAvailable", vals.get("MemFree", 0))
    except Exception:
        pass
    return 0, 0


def _vram():
    """(total_mb, free_mb) from nvidia-smi, or (0, 0) when there is no NVIDIA card or no driver."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return 0, 0
    try:
        out = subprocess.run([smi, "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15).stdout.strip().splitlines()
        total = used = 0
        for row in out:
            t, u = (x.strip() for x in row.split(",")[:2])
            total += int(t or 0)
            used += int(u or 0)
        return total, max(total - used, 0)
    except Exception:
        return 0, 0


def _health(url, timeout):
    """Seconds to answer, or None when nothing answers."""
    if not url:
        return None
    started = time.time()
    try:
        req = urllib.request.Request(url.rstrip("/") + "/health", headers={"Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout):
            return round(time.time() - started, 3)
    except Exception:
        try:
            req = urllib.request.Request(url.rstrip("/") + "/api/tags")
            with urllib.request.urlopen(req, timeout=timeout):
                return round(time.time() - started, 3)
        except Exception:
            return None


def sample(server_url="", thresholds=None):
    th = {**THRESHOLDS, **(thresholds or {})}
    total_ram, free_ram = _ram()
    total_vram, free_vram = _vram()
    health = _health(server_url, th["health_s"]) if server_url else None
    reasons = []
    if free_ram and free_ram < th["free_ram_mb"]:
        reasons.append(f"free RAM {free_ram} MB < {th['free_ram_mb']} MB")
    if free_vram and total_vram and free_vram < th["free_vram_mb"]:
        reasons.append(f"free VRAM {free_vram} MB < {th['free_vram_mb']} MB")
    if server_url and health is None:
        reasons.append(f"the server at {server_url} did not answer within {th['health_s']}s")
    elif health is not None and health > th["health_s"]:
        reasons.append(f"the server took {health}s to answer (limit {th['health_s']}s)")
    return {"ts": round(time.time(), 3), "total_ram_mb": total_ram, "free_ram_mb": free_ram,
            "total_vram_mb": total_vram, "free_vram_mb": free_vram, "health_s": health,
            "reasons": reasons, "bad": bool(reasons)}


class Watchdog:
    """Escalates only on consecutive bad samples, and forgets the count the moment the machine recovers."""

    def __init__(self, server_url="", thresholds=None, unload=None, kill=None, flag=None,
                 log_path=None, interval=INTERVAL, sampler=None):
        self.server_url = server_url
        self.th = {**THRESHOLDS, **(thresholds or {})}
        self.unload, self.kill, self.flag = unload, kill, flag
        self.log_path = Path(log_path or LOG)
        self.interval = interval
        self._sampler = sampler or sample
        self.streak = 0
        self.level = 0            # index into LEVELS of the last action taken
        self.history = []

    def _write(self, entry):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass
        self.history.append(entry)

    def check(self, task_id=""):
        """One sample, one decision. Returns the level it reached."""
        s = self._sampler(self.server_url, self.th)
        if s["bad"]:
            self.streak += 1
        else:
            self.streak = 0
            self.level = 0
            self._write({**s, "level": "ok", "task": task_id})
            return "ok"
        need = self.th["consecutive"]
        if self.streak < need:
            level = "ok"                                  # a blip is not an incident
        else:
            # One step per sustained incident: warn, then unload, then kill, then hand the task back.
            self.level = min(self.level + 1, len(LEVELS) - 1)
            level = LEVELS[self.level]
        entry = {**s, "level": level, "streak": self.streak, "task": task_id}
        if level == "unload" and self.unload:
            entry["action"] = _safe(self.unload)
        elif level == "kill" and self.kill:
            entry["action"] = _safe(self.kill)
        elif level == "flag" and self.flag:
            entry["action"] = _safe(self.flag, task_id, "; ".join(s["reasons"]))
        self._write(entry)
        return level

    def run(self, task_id="", stop=None, max_samples=None):
        """Loop until `stop()` is true or max_samples is reached. Deterministic: same samples, same actions."""
        n = 0
        while not (stop and stop()):
            self.check(task_id)
            n += 1
            if max_samples is not None and n >= max_samples:
                return n
            time.sleep(self.interval)
        return n


def _safe(fn, *args):
    try:
        return str(fn(*args) or "done")
    except Exception as e:
        return f"failed: {e}"


def main(argv):
    argv = list(argv or [])
    from . import serving
    try:
        srv = serving.active()
        url = srv.get("url") or ""
    except serving.ServingError:
        url = ""
    # A single check from the command line; `serve` runs the continuous form with the escalation callbacks wired.
    s = sample(url)
    print(f"free RAM {s['free_ram_mb']} MB / {s['total_ram_mb']} MB"
          f"  ·  free VRAM {s['free_vram_mb']} MB / {s['total_vram_mb']} MB"
          f"  ·  health {s['health_s']}")
    if s["reasons"]:
        print("would escalate: " + "; ".join(s["reasons"]))
        return 1
    print("ok - nothing to escalate")
    return 0
