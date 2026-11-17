"""Model catalog (serving/models.yaml): which models a plan may pick, whether they are installed, and fetching them.

A plan names a model per step; the person signs off on those choices; the worker makes sure every chosen model is
installed before the first step runs. Weights live in models/<name>/ (Hugging Face) or are Ollama blobs.
"""
import json
import re
import shutil
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import paths
from . import yamlio as yaml

CATALOG = paths.ROOT / "serving" / "models.yaml"
PINS = paths.STATE / "model-pins.json"
DEFAULT_ARGS = "-fa on -ctk q8_0 -ctv q8_0 --jinja -ngl 99"          # agents also get -c <context.window>
GENERATE_ARGS = "-c 16384 -fa on --jinja -ngl 99"
CONTEXT = {"window": 98304, "compress_at": 70000}
KINDS = ("agent", "generate", "image", "embed")


class ModelError(ValueError):
    pass


@dataclass
class Model:
    name: str
    kind: str
    roles: list
    about: str = ""
    size_gb: float = 0
    weights: dict = field(default_factory=dict)   # part -> {repo, file|dir, sha256?}; one part may be the entry itself
    ollama: dict = field(default_factory=dict)    # {tag, blob}
    args: str = ""
    sd_args: str = ""

    @property
    def parts(self):
        """{part: spec}. A single {repo, file} entry is the part 'model'."""
        w = self.weights or {}
        return {"model": w} if "repo" in w else dict(w)

    @property
    def dir(self):
        return paths.MODELS / self.name

    def part_path(self, part="model"):
        """Local path of a part: the file, or for a split GGUF (dir) the first shard."""
        spec = self.parts[part]
        if "file" in spec:
            return self.dir / spec["file"].split("/")[-1]
        shards = sorted((self.dir / spec["dir"]).glob("*.gguf")) if (self.dir / spec["dir"]).exists() else []
        return shards[0] if shards else self.dir / spec["dir"] / "(missing)"

    def gguf(self):
        """The weights file llama-server loads."""
        if self.ollama:
            return paths.ollama_blobs() / self.ollama["blob"]
        return self.part_path("model")

    def installed(self):
        if self.ollama:
            return self.gguf().exists()
        return bool(self.parts) and all(self.part_path(p).exists() for p in self.parts)

    def line(self):
        state = "installed" if self.installed() else f"not installed, {self.size_gb:g} GB to fetch"
        return f"- {self.name} [{self.kind}; for {', '.join(self.roles)}; {state}]: {self.about}"


@dataclass
class Catalog:
    models: dict
    defaults: dict
    context: dict = field(default_factory=lambda: dict(CONTEXT))

    def get(self, name):
        if name not in self.models:
            raise ModelError(f"no model '{name}' in serving/models.yaml (have: {', '.join(self.models)})")
        return self.models[name]

    def default_for(self, role, fallback=None):
        return self.defaults.get(role) or fallback

    def pickable(self):
        """Models a plan may assign to a step (not the router or embeddings)."""
        return [m for m in self.models.values() if m.kind in ("agent", "generate", "image") and "router" not in m.roles]

    def text(self):
        return "\n".join(m.line() for m in self.pickable())


def load(path=None):
    data = yaml.safe_load((path or CATALOG).read_text(encoding="utf-8-sig")) or {}
    models = {}
    for name, d in (data.get("models") or {}).items():
        if d.get("kind") not in KINDS:
            raise ModelError(f"model {name}: kind must be one of {KINDS}")
        models[name] = Model(name=name, kind=d["kind"], roles=list(d.get("roles") or []), about=d.get("about", ""),
                             size_gb=float(d.get("size_gb") or 0), weights=d.get("weights") or {},
                             ollama=d.get("ollama") or {}, args=d.get("args", ""), sd_args=d.get("sd_args", ""))
    defaults = dict(data.get("defaults") or {})
    for role, name in defaults.items():
        if name not in models:
            raise ModelError(f"default for {role} is '{name}', which is not in the catalog")
    context = {**CONTEXT, **(data.get("context") or {})}
    if not 0 < int(context["compress_at"]) < int(context["window"]):
        raise ModelError("context.compress_at must be below context.window")
    for m in models.values():
        if m.kind == "agent" and re.search(r"(^|\s)(-c|--ctx-size)\s", m.args):
            raise ModelError(f"model {m.name}: set the window in context.window, not with -c in args")
    return Catalog(models, defaults, {k: int(v) for k, v in context.items()})


# ---------- llama-swap entries ----------

def swap_entries(catalog=None):
    """llama-swap `models:` entries for every agent/generate/embed model (they start only when asked for)."""
    from .kvcache import KV_DIR
    cat = catalog or load()
    out = {}
    for m in cat.models.values():
        if m.kind == "image":
            continue
        args = m.args or (GENERATE_ARGS if m.kind == "generate" else DEFAULT_ARGS)
        if m.kind == "agent":
            args = f"-c {cat.context['window']} " + args  # sessions can park their KV cache on disk (kvcache.py)
            args += f' --slot-save-path "{KV_DIR.as_posix()}"'
        out[m.name] = {"cmd": f'${{server}} ${{common}} {args} -m "{m.gguf().as_posix()}"', "ttl": 900}
    return out


# ---------- fetching ----------

def _pins():
    try:
        return json.loads(PINS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_pins(pins):
    paths.ensure()
    PINS.write_text(json.dumps(pins, indent=1, sort_keys=True), encoding="utf-8")


def _hf_tree(repo, path=""):
    """Files under `path` in a Hugging Face repo: [{path, size, sha256}] (sha256 = the LFS oid)."""
    url = f"https://huggingface.co/api/models/{repo}/tree/main/{urllib.parse.quote(path)}".rstrip("/")
    with urllib.request.urlopen(url, timeout=60) as r:
        items = json.loads(r.read())
    return [{"path": i["path"], "size": i.get("size", 0), "sha256": (i.get("lfs") or {}).get("oid")}
            for i in items if i.get("type") == "file"]


def plan_fetch(model):
    """[(url, dest, sha256, size)] for every missing file of `model`. Network: the Hugging Face API listing."""
    if model.ollama:
        return []
    pins, todo = _pins(), []
    for part, spec in model.parts.items():
        repo = spec["repo"]
        if "file" in spec:
            parent = spec["file"].rsplit("/", 1)[0] if "/" in spec["file"] else ""
            files = [f for f in _hf_tree(repo, parent) if f["path"] == spec["file"]]
            dests = [model.dir / spec["file"].split("/")[-1]]
        else:
            files = sorted((f for f in _hf_tree(repo, spec["dir"]) if f["path"].endswith(".gguf")),
                           key=lambda f: f["path"])
            dests = [model.dir / spec["dir"] / f["path"].split("/")[-1] for f in files]
        if not files:
            raise ModelError(f"{model.name}: {repo} has no {spec.get('file') or spec.get('dir')}")
        for f, dest in zip(files, dests):
            key = f"{repo}/{f['path']}"
            expected = spec.get("sha256") if "file" in spec else None
            pinned = pins.get(key)
            if pinned and f["sha256"] and pinned != f["sha256"]:
                raise ModelError(f"{key}: Hugging Face now serves sha256 {f['sha256']}, pinned {pinned}. "
                                 f"Delete its entry in {PINS} only if you trust the new file.")
            sha = expected or pinned or f["sha256"]
            if not sha:
                raise ModelError(f"{key}: no sha256 to verify against")
            pins[key] = sha
            if not dest.exists():
                url = f"https://huggingface.co/{repo}/resolve/main/{urllib.parse.quote(f['path'])}"
                todo.append((url, dest, sha, f["size"]))
    _save_pins(pins)
    return todo


def install(name, catalog=None, log=print):
    """Fetch a model's weights (verified), or pull it with Ollama. Raises ModelError with a fix on failure."""
    from . import deps
    m = (catalog or load()).get(name)
    if m.installed():
        return
    if m.ollama:
        if not deps.has_tool("ollama"):
            raise ModelError(f"{name} comes from Ollama, which is not installed: python -m ariadne install --system")
        log(f"ollama pull {m.ollama['tag']}")
        r = deps._run(["ollama", "pull", m.ollama["tag"]])
        if r.returncode != 0 or not m.installed():
            raise ModelError(f"ollama pull {m.ollama['tag']} failed: {r.stderr[-500:]}")
        return
    todo = plan_fetch(m)
    need = sum(t[3] for t in todo)
    paths.MODELS.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(paths.MODELS).free
    if need > free - 2 * 2**30:
        raise ModelError(f"{name} needs {need / 2**30:.1f} GB; {free / 2**30:.1f} GB free under {paths.MODELS}")
    for url, dest, sha, size in todo:
        log(f"fetching {dest.relative_to(paths.MODELS)} ({size / 2**30:.1f} GB)")
        dest.parent.mkdir(parents=True, exist_ok=True)
        deps.download(url, dest, sha)


def missing(names, catalog=None):
    cat = catalog or load()
    return [n for n in dict.fromkeys(names) if not cat.get(n).installed()]


def main(argv):
    """python -m ariadne models [list | install NAME...]"""
    cat = load()
    if not argv or argv[0] == "list":
        print("defaults: " + ", ".join(f"{r}={n}" for r, n in cat.defaults.items()))
        print("\n".join(m.line() for m in cat.models.values()))
        return 0
    if argv[0] == "install" and argv[1:]:
        names = list(dict.fromkeys(cat.defaults.values())) if argv[1:] == ["--defaults"] else argv[1:]
        for n in names:
            try:
                install(n, cat)
                print(f"{n}: installed")
            except ModelError as e:
                print(f"{n}: {e}")
                return 1
        return 0
    print(main.__doc__)
    return 2
