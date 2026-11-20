"""Resource profiles: how much of this machine the local models may take.

  max     everything for Ariadne: VRAM filled to the brim, the rest of the model on the CPU in RAM, pinned there
          (no paging), high priority - but model weights get at most 80% of RAM, so Windows keeps room.
  shared  as much as possible while you keep working: VRAM with a little headroom, the rest on the CPU in RAM,
          normal priority.

Neither pushes model weights into Windows "shared GPU memory": measured on an 8 GB RTX 3070 with the 27B, placing
14.6 GB there made decoding ~6x slower (0.35 vs 2.17 tok/s) because the GPU reads it over PCIe on every token. RAM
is used by the CPU half of the model instead - same memory, much faster.
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
LIMITS = paths.STATE / "limits.json"
MAX_GPU_SHARE = 1.0   # max profile: all of GPU memory (llama.cpp keeps its own 256 MiB margin)
MAX_RAM_SHARE = 0.8   # max profile: at most this share of RAM for model weights


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
        # Everything for Ariadne, inside one hard limit: all of the GPU, but at most 80% of RAM for model weights, so
        # Windows and the rest of the machine keep room (pinning 90% of RAM crashed the PC).
        fit_mib, prio, extra = max(256, int(vram * (1 - MAX_GPU_SHARE) * 1024)), 2, "-lm mmap+mlock"
        cap = vram * MAX_GPU_SHARE + ram * MAX_RAM_SHARE
    elif profile == "light":
        fit_mib, prio, extra, cap = int(vram * 0.2 * 1024), -1, "", vram * 0.8 + ram * 0.5
    else:
        fit_mib, prio, extra, cap = 768, 0, "", vram + ram * 0.75
    args = f"--fit-target {fit_mib} --prio {prio}" + (f" {extra}" if extra else "")
    return {"profile": profile, "vram_gb": vram, "ram_gb": ram, "shared_gpu_gb": shared,
            "fit_args": args, "max_model_gb": round(cap, 1)}


def describe(b):
    use = {"max": f"all of GPU memory, at most {MAX_RAM_SHARE:.0%} of RAM (pinned), high priority",
           "shared": "VRAM with headroom, the rest on the CPU in RAM, normal priority",
           "light": "at most 80% of GPU memory and 50% of RAM, low priority"}[b["profile"]]
    return (f"{b['profile']}: {use}\n  machine: {b['vram_gb']} GB GPU, {b['ram_gb']} GB RAM "
            f"({b['shared_gpu_gb']} GB shareable with the GPU)\n  llama-server: {b['fit_args']}\n"
            f"  largest model allowed: {b['max_model_gb']} GB")


def detect_at_boot(profile=None, log=print):
    """Measure this machine and record what the profile allows (.ariadne/limits.json). Run when the model server or
    the worker starts, so limits follow the hardware actually present (a new GPU, more RAM, another machine)."""
    import json
    import time
    from . import models
    b = budget(profile or current(models.load().resources))
    if not b["vram_gb"]:
        log("limits: no NVIDIA GPU detected; models run on the CPU")
    b["detected"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        LIMITS.parent.mkdir(parents=True, exist_ok=True)
        LIMITS.write_text(json.dumps(b, indent=2), encoding="utf-8")
    except OSError:
        pass
    log("limits: " + describe(b).replace("\n", "\n        "))
    try:
        # The shortlist, from the same measurement: the catalog the planner may pick from is what this can run.
        from . import modelindex
        rows = modelindex.shortlist(models.load(), modelindex.scan(vram=b["vram_gb"], ram=b["ram_gb"]))
        fast = sum(1 for v in rows if v.tier == "gpu")
        run = sum(1 for v in rows if v.tier != "no")
        log(f"models: {run} of {len(rows)} in the catalog can run here ({fast} fit in VRAM); "
            f"`ariadne models index` for the list")
    except Exception as e:
        log(f"models: could not index the catalog ({e})")
    return b


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
