"""The model index: what this machine can run, and the shortlist of the catalog that fits it.

The catalog (`serving/models.yaml`) is a closed set; the index is the deterministic filter over it. At startup Ariadne
measures the device - GPU, VRAM, RAM, CPU, free disk - and turns that into two capacities: what fits inside VRAM (the
fast tier) and what the active resource profile allows in total (VRAM plus the share of RAM a model may use). Every
catalog model then gets a verdict - `gpu`, `hybrid` or `no` - with the arithmetic in the reason, so a task is never
offered a model this machine cannot run, and never silently downgraded either.

`pulse()` is the non-deterministic half and is deliberately separate: it asks Hugging Face for the most downloaded
models of a task, filters them through the same arithmetic, and returns suggestions. It never edits the catalog -
admitting a suggestion is a person's decision, because the catalog is a closed set.

Sizing is honest rather than precise: a model needs its weights plus `OVERHEAD_GB` for the KV cache at the catalog's
64K window, CUDA context and buffers. That constant is the same for every model, which is what makes the verdict
deterministic and testable; it is not a promise about tokens per second.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from . import paths, resources
from .models import OVERHEAD_GB

GPU_HEADROOM = 0.9           # leave a tenth of VRAM for the desktop and the server's own allocations
PULSE_CACHE = paths.STATE / "hf-pulse.json"
TASKS = {"agent": "text-generation", "generate": "text-generation",
         "image": "text-to-image", "embed": "feature-extraction"}


@dataclass(frozen=True)
class Device:
    os: str
    arch: str
    cpu: str
    cores: int
    ram_gb: float
    vram_gb: float
    gpu: str
    backend: str             # cuda | metal | cpu
    disk_free_gb: float

    def line(self):
        gpu = f"{self.gpu}, {self.vram_gb:g} GB VRAM" if self.vram_gb else f"{self.gpu} (no discrete GPU)"
        return (f"{gpu}; {self.ram_gb:g} GB RAM; {self.cpu}, {self.cores} cores; {self.backend}; "
                f"{self.disk_free_gb:g} GB free for weights")


def _gpu_name(nvidia_smi=None):
    exe = nvidia_smi or shutil.which("nvidia-smi")
    if not exe:
        return "CPU only"
    try:
        out = subprocess.run([exe, "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
        return out[0].strip() if out else "NVIDIA GPU"
    except (OSError, subprocess.TimeoutExpired):
        return "NVIDIA GPU"


def _disk_free_gb():
    target = paths.MODELS if paths.MODELS.exists() else paths.ROOT
    try:
        return round(shutil.disk_usage(str(target)).free / 1e9, 1)
    except OSError:
        return 0.0


def scan(vram=None, ram=None, gpu=None, disk_free=None):
    """Measure this machine. Every probe is injectable so a test (or another machine) can describe a device."""
    vram = resources.vram_gb() if vram is None else float(vram)
    ram = resources.ram_gb() if ram is None else float(ram)
    if sys.platform == "darwin" and platform.machine().lower() in ("arm64", "aarch64"):
        backend = "metal"
    elif vram:
        backend = "cuda"
    else:
        backend = "cpu"
    return Device(os=sys.platform, arch=platform.machine(), cpu=platform.processor() or platform.machine(),
                  cores=os.cpu_count() or 1, ram_gb=round(ram, 1), vram_gb=round(vram, 1),
                  gpu=(gpu if gpu is not None else _gpu_name()), backend=backend,
                  disk_free_gb=(round(float(disk_free), 1) if disk_free is not None else _disk_free_gb()))


def capacity(device, profile="shared"):
    """The two numbers the verdict uses: what fits in VRAM, and the most a model may take in total."""
    budget = resources.budget(profile, vram=device.vram_gb, ram=device.ram_gb)
    return {"profile": profile, "gpu_gb": round(device.vram_gb * GPU_HEADROOM, 1),
            "total_gb": budget["max_model_gb"], "fit_args": budget["fit_args"]}


@dataclass
class Verdict:
    name: str
    kind: str
    size_gb: float
    need_gb: float           # weights + the fixed overhead
    tier: str                # gpu | hybrid | no
    reason: str


def verdict(model, device, profile="shared"):
    """Where one catalog model lands on this machine, with the arithmetic in the reason."""
    cap = capacity(device, profile)
    need = round((model.size_gb or 0) + OVERHEAD_GB, 1)
    if need <= cap["gpu_gb"]:
        return Verdict(model.name, model.kind, model.size_gb, need, "gpu",
                       f"{need:g} GB fits in {device.vram_gb:g} GB VRAM")
    if need <= cap["total_gb"]:
        moe = " (MoE: only its active parameters are computed, so CPU offload costs less)" if model.moe else ""
        return Verdict(model.name, model.kind, model.size_gb, need, "hybrid",
                       f"{need:g} GB of {cap['total_gb']:g} GB: runs with part of the weights on the CPU{moe}")
    return Verdict(model.name, model.kind, model.size_gb, need, "no",
                   f"needs {need:g} GB; this machine allows {cap['total_gb']:g} GB")


def shortlist(catalog, device=None, profile=None):
    """Every catalog model with a verdict, in a stable order (catalog order)."""
    device = device or scan()
    profile = profile or catalog.resources
    return [verdict(m, device, profile) for m in catalog.models.values()]


def available(catalog, device=None, profile=None):
    """The options a task may be offered: everything the machine can run, fast tier first."""
    rows = shortlist(catalog, device, profile)
    return sorted([v for v in rows if v.tier != "no"], key=lambda v: {"gpu": 0, "hybrid": 1}[v.tier])


def report(catalog, device=None, profile=None):
    device = device or scan()
    profile = profile or catalog.resources
    cap = capacity(device, profile)
    rows = shortlist(catalog, device, profile)
    head = [f"device: {device.line()}",
            f"profile {cap['profile']}: {cap['gpu_gb']:g} GB fits in VRAM; {cap['total_gb']:g} GB is the most a "
            f"model may take ({len(catalog.models)} in the catalog, {sum(1 for v in rows if v.tier != 'no')} can run)"]
    tiers = (("gpu", "fits in VRAM (fast)"), ("hybrid", "runs with CPU offload (slower)"), ("no", "cannot run here"))
    for tier, label in tiers:
        group = [v for v in rows if v.tier == tier]
        if not group:
            continue
        head.append(f"\n{label}:")
        head += [f"  - {v.name} [{v.kind}, {v.size_gb:g} GB] {v.reason}" for v in group]
    return "\n".join(head)


# ---------- the pulse: Hugging Face suggestions, filtered by the same arithmetic ----------

def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _hf(task, limit=100):
    url = ("https://huggingface.co/api/models?" + urllib.parse.urlencode(
        {"filter": task, "sort": "downloads", "direction": -1, "limit": min(int(limit), 200),
         "expand[]": "safetensors"}))          # the plain list omits parameter counts; ask for them
    req = urllib.request.Request(url, headers={"User-Agent": "ariadne-model-index"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _est_size_gb(row):
    """A 4-bit size estimate from the parameter count Hugging Face reports; None when it does not report one."""
    total = ((row.get("safetensors") or {}).get("total") or 0)
    if not total:
        return None
    return round(total / 1e9 * 0.6, 1)          # q4_k_m is about 0.6 bytes per parameter


def pulse(kind="agent", device=None, profile="shared", limit=10, fetch=None, max_age_h=24, refresh=False,
          cache=PULSE_CACHE):
    """Top downloaded Hugging Face models for a task, cut to what this machine can run. Returns (rows, note).

    `fetch(task)` is injectable; the answer is cached for `max_age_h` so a startup does not hit the network every
    time, and `refresh=True` polls again. A model without a parameter count is skipped rather than guessed at.
    """
    task = TASKS.get(kind, kind)
    cached = _load(cache)
    fresh = (cached.get("task") == task and not refresh
             and time.time() - float(cached.get("fetched") or 0) < max_age_h * 3600)
    rows = cached.get("rows") if fresh else None
    note = ""
    if rows is None:
        try:
            rows = (fetch or _hf)(task)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"task": task, "fetched": time.time(), "rows": rows}, ensure_ascii=False),
                             encoding="utf-8")
        except Exception as e:
            return [], f"hugging face did not answer: {type(e).__name__}: {e}"
    device = device or scan()
    cap = capacity(device, profile)
    out = []
    for row in rows or []:
        size = _est_size_gb(row)
        if size is None or size + OVERHEAD_GB > cap["total_gb"]:
            continue
        out.append({"id": row.get("id"), "task": row.get("pipeline_tag") or task, "downloads": row.get("downloads") or 0,
                    "likes": row.get("likes") or 0, "size_gb": size,
                    "tier": "gpu" if size + OVERHEAD_GB <= cap["gpu_gb"] else "hybrid"})
    out.sort(key=lambda r: r["downloads"], reverse=True)
    return out[:max(1, int(limit))], note


def main(argv):
    """python -m ariadne models index [--json] [--pulse agent|image|embed] [--refresh]"""
    from . import models as modellib
    cat = modellib.load()
    device = scan()
    if "--json" in argv:
        print(json.dumps({"device": asdict(device), "capacity": capacity(device, cat.resources),
                          "models": [asdict(v) for v in shortlist(cat, device)]}, indent=2))
        return 0
    print(report(cat, device))
    if "--pulse" in argv:
        i = argv.index("--pulse")
        kind = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else "agent"
        rows, note = pulse(kind, device, refresh="--refresh" in argv)
        print(f"\nhugging face pulse ({kind}, top {len(rows)} that fit):")
        for r in rows:
            print(f"  - {r['id']} [{r['tier']}, ~{r['size_gb']:g} GB q4, {r['downloads']:,} downloads]")
        if note:
            print(f"  ({note})")
        print("  (suggestions only: the catalog is a closed set; admitting one is a person's decision)")
    return 0
