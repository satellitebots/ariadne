"""Resource profiles: how much of this machine the local models may take.

  max     everything for Ariadne: GPU memory plus ~90% of Windows shared GPU memory, high priority, model pinned in
          RAM (no paging). Other apps will feel it.
  shared  as much as possible while you keep working: GPU memory plus half of shared GPU memory, normal priority.
  light   a budget: at most 80% of GPU memory and 50% of RAM for a model, low priority; models that do not fit
          that budget are not offered to the planner.

Set with `python -m ariadne resources <profile>`; the worker applies it between tasks (the model server restarts
its models, so never in the middle of a run). The default is in serving/models.yaml (resources.profile).
"""
import ctypes
import os
import shutil
import subprocess

from . import paths

PROFILES = ("max", "shared", "light")
CHOICE = paths.STATE / "resources"


def vram_gb():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0.0
    try:
        out = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=10).stdout.split()
        return round(float(out[0]) / 1024, 1) if out else 0.0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def ram_gb():
    if paths.WINDOWS:
        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("pf_total", ctypes.c_ulonglong),
                        ("pf_avail", ctypes.c_ulonglong), ("v_total", ctypes.c_ulonglong),
                        ("v_avail", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
        s = Status()
        s.length = ctypes.sizeof(Status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        return round(s.total / 2**30, 1)
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        return 0.0


def shared_gpu_gb(ram):
    """Windows lets the GPU borrow up to half of system RAM ("shared GPU memory"); elsewhere CUDA cannot."""
    return round(ram / 2, 1) if paths.WINDOWS else 0.0


def current(default="shared"):
    try:
        p = CHOICE.read_text(encoding="utf-8").strip()
    except OSError:
        p = ""
    return p if p in PROFILES else (default if default in PROFILES else "shared")


def choose(profile):
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}")
    paths.ensure()
    CHOICE.write_text(profile, encoding="utf-8")


def budget(profile, vram=None, ram=None):
    """What a profile allows on this machine: llama-server arguments for models that do not fit the GPU (--fit on),
    and the largest model size it will run."""
    vram = vram_gb() if vram is None else vram
    ram = ram_gb() if ram is None else ram
    shared = shared_gpu_gb(ram)
    if profile == "max":
        fit_mib, prio, extra, cap = -int(shared * 0.9 * 1024), 2, "-lm mmap+mlock", vram + ram * 0.9
    elif profile == "light":
        fit_mib, prio, extra, cap = int(vram * 0.2 * 1024), -1, "", vram * 0.8 + ram * 0.5
    else:
        fit_mib, prio, extra, cap = -int(shared * 0.5 * 1024), 0, "", vram + ram * 0.75
    args = f"--fit-target {fit_mib} --prio {prio}" + (f" {extra}" if extra else "")
    return {"profile": profile, "vram_gb": vram, "ram_gb": ram, "shared_gpu_gb": shared,
            "fit_args": args, "max_model_gb": round(cap, 1)}


def describe(b):
    use = {"max": "GPU memory + ~90% of shared GPU memory, high priority, model pinned in RAM",
           "shared": "GPU memory + half of shared GPU memory, normal priority",
           "light": "at most 80% of GPU memory and 50% of RAM, low priority"}[b["profile"]]
    return (f"{b['profile']}: {use}\n  machine: {b['vram_gb']} GB GPU, {b['ram_gb']} GB RAM "
            f"({b['shared_gpu_gb']} GB shareable with the GPU)\n  llama-server: {b['fit_args']}\n"
            f"  largest model allowed: {b['max_model_gb']} GB")


def main(argv):
    """python -m ariadne resources [max | shared | light]"""
    from . import models
    default = models.load().resources
    if argv:
        if argv[0] not in PROFILES:
            print(main.__doc__)
            return 2
        choose(argv[0])
        print("set; the worker applies it before the next task")
    print(describe(budget(current(default))))
    return 0
