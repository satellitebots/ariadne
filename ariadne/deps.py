"""Dependencies: check them (`doctor`) and install what is missing (`install`), on Windows, Linux and macOS.

Standard library only, so it runs before the Python environment exists:  uv run python -m ariadne install
Everything is pinned: Hermes by submodule commit, Python packages by Hermes's uv.lock, binaries by sha256
(serving/bin.lock), Ollama models by tag. Other model weights come from the catalog (serving/models.yaml, ariadne/models.py),
sha256-pinned on first fetch. System tools (git, uv, node, ollama) are
installed with the platform's package manager only when you pass --system; otherwise their install command is shown.
"""
import hashlib
import json
import shutil
import platform
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass, field

from . import paths

OLLAMA_MODELS = ["qwen3.5:9b", "qwen3.5:4b", "qwen3-embedding:0.6b"]
SYSTEM_TOOLS = {  # name: (command to find, why, {package manager: install command})
    "git": ("git", "source control, the Hermes submodule",
            {"winget": "winget install -e --id Git.Git", "brew": "brew install git", "apt": "sudo apt-get install -y git"}),
    "uv": ("uv", "Python and the pinned environment",
           {"winget": "winget install -e --id astral-sh.uv", "brew": "brew install uv",
            "sh": "curl -LsSf https://astral.sh/uv/install.sh | sh"}),
    "ollama": ("ollama", "stores the model weights; fallback model server",
               {"winget": "winget install -e --id Ollama.Ollama", "brew": "brew install ollama",
                "sh": "curl -fsSL https://ollama.com/install.sh | sh"}),
    "node": ("npx", "runs the Chrome browser MCP server (browser flows)",
             {"winget": "winget install -e --id OpenJS.NodeJS.LTS", "brew": "brew install node",
              "apt": "sudo apt-get install -y nodejs npm"}),
}
OPTIONAL_TOOLS = {"node"}  # flows that need it declare it in flow.yaml `requires`


@dataclass
class Check:
    name: str
    ok: bool
    why: str
    fix: str = ""          # command to run, or "auto" when `install` fixes it
    required: bool = True


@dataclass
class Report:
    checks: list = field(default_factory=list)

    @property
    def missing(self):
        return [c for c in self.checks if not c.ok and c.required]

    def text(self):
        lines = []
        for c in self.checks:
            mark = "ok      " if c.ok else ("MISSING " if c.required else "optional")
            lines.append(f"  {mark} {c.name}" + ("" if c.ok else f"  - {c.why}" + (f"\n             fix: {c.fix}" if c.fix else "")))
        return "\n".join(lines)


# ---------- lock files ----------

def read_lock(name):
    rows = []
    for line in (paths.ROOT / "serving" / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(line.split("|"))
    return rows


def bin_entries(platform_key=None):
    key = platform_key or paths.platform_key()
    return [dict(name=r[0], version=r[1], platform=r[2], url=r[3], sha256=r[4]) for r in read_lock("bin.lock")
            if r[2] == key]


def bin_dir(entry):
    engine = entry["name"][:-3] if entry["name"].endswith("-rt") else entry["name"]
    return paths.BIN / f"{engine}-{entry['version']}"


def find_bin(name, exe):
    """Path of an executable from a pinned binary, e.g. find_bin('llama.cpp', 'llama-server')."""
    hits = sorted(paths.BIN.glob(f"{name}-*/**/{exe}{paths.EXE}"))
    return hits[-1] if hits else None


# ---------- download, verify, extract ----------

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, expected):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and sha256(dest) == expected:
        return dest
    part = dest.with_name(dest.name + ".part")
    curl = shutil.which("curl")
    if curl:  # resumable, with progress
        subprocess.run([curl, "-L", "--fail", "--retry", "3", "-C", "-", "-o", str(part), url], check=True)
    else:
        with urllib.request.urlopen(url) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    got = sha256(part)
    if got != expected:
        part.unlink()
        raise RuntimeError(f"sha256 mismatch for {url}: got {got}, expected {expected} (file deleted)")
    part.replace(dest)
    return dest


def extract(archive, dest):
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="data")
    if not paths.WINDOWS:  # zip loses the executable bit
        for p in dest.rglob("*"):
            if p.is_file() and (p.suffix in ("", ".so", ".dylib") or ".so." in p.name):
                p.chmod(p.stat().st_mode | 0o111)


def fetch_bin(entry):
    archive = download(entry["url"], paths.BIN / "_downloads" / entry["url"].rsplit("/", 1)[-1], entry["sha256"])
    extract(archive, bin_dir(entry))


# ---------- checks ----------

def package_manager():
    if paths.WINDOWS:
        return "winget" if shutil.which("winget") else ""
    if sys.platform == "darwin":
        return "brew" if shutil.which("brew") else ""
    return "apt" if shutil.which("apt-get") else "sh"


def tool_fix(name):
    recipes = SYSTEM_TOOLS[name][2]
    pm = package_manager()
    return recipes.get(pm) or recipes.get("sh") or next(iter(recipes.values()))


def has_tool(name):
    return bool(shutil.which(SYSTEM_TOOLS[name][0] + (".cmd" if paths.WINDOWS and name == "node" else "")) or
                shutil.which(SYSTEM_TOOLS[name][0]))


def chrome_path():
    for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if shutil.which(c):
            return shutil.which(c)
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if paths.Path(p).exists():
            return p
    return None


def gpu():
    if sys.platform == "darwin":
        return paths.platform_key() == "darwin-arm64", "Apple Silicon (Metal)"
    return bool(shutil.which("nvidia-smi")), "NVIDIA driver (nvidia-smi)"


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def submodule_pin():
    out = _run(["git", "-C", str(paths.ROOT), "ls-files", "-s", "vendor/hermes"]).stdout.split()
    return out[1] if len(out) > 1 else ""


def check(full=True):
    """What is there and what is missing. full=False: only what running tasks needs (fast).

    Besides the system tools, three things a person has to be able to see: the Python the venv runs, where inference is
    and whether it answers (`serving.active()`), and per flow the tools it declares - because a flow that cannot get
    its requirements is refused before a plan, and this is how you find that out without giving it a task.
    """
    r = Report()
    add = r.checks.append
    add(Check(f"Python {platform.python_version()}", sys.version_info >= (3, 12),
              "Ariadne needs 3.12 or newer", "uv python install 3.14"))
    for name, (cmd, why, _) in SYSTEM_TOOLS.items():
        add(Check(f"{name}", has_tool(name), why, tool_fix(name), required=name not in OPTIONAL_TOOLS))
    ok, label = gpu()
    add(Check(f"GPU: {label}", ok, "local models need a GPU (CPU works, but slowly)", "", required=False))
    add(Check("Chrome", bool(chrome_path()), "the visible browser (browser flows)",
              "install Google Chrome from google.com/chrome", required=False))
    _server_check(add)
    _flow_checks(add)
    pin = submodule_pin() if shutil.which("git") else ""
    head = _run(["git", "-C", str(paths.UPSTREAM), "rev-parse", "HEAD"]).stdout.strip() if (paths.UPSTREAM / ".git").exists() else ""
    add(Check(f"Hermes submodule at {pin[:10] or '?'}", bool(pin) and head == pin, "the agent engine", "auto"))
    venv_ok = paths.VENV_PY.exists() and _run(
        [str(paths.VENV_PY), "-c", "import mcp, fastapi, uvicorn, ddgs, ruamel.yaml, run_agent"]).returncode == 0
    add(Check("Python env (.venv: Hermes + MCP SDK)", venv_ok, "Hermes and Ariadne's Python dependencies", "auto"))
    entries = bin_entries()
    if not entries:
        add(Check(f"binaries for {paths.platform_key()}", False, "no pinned binaries for this platform", ""))
    for e in entries:
        present = bin_dir(e).exists() and any(bin_dir(e).iterdir())
        add(Check(f"{e['name']} {e['version']}", present, "pinned binary, sha256-verified", "auto"))
    try:  # the catalog needs the venv (ruamel); before install there is nothing to report
        from . import models as modellib
        cat = modellib.load()
    except ImportError:
        cat = None
    for m in (cat.models.values() if cat else []):
        if not m.ollama:
            add(Check(f"model {m.name}", m.installed(), f"{m.kind} model, {m.size_gb:g} GB (fetched when a plan picks it)",
                      f"python -m ariadne models install {m.name}", required=False))
    if full and has_tool("ollama"):
        listed = _run(["ollama", "list"]).stdout
        for tag in OLLAMA_MODELS + [p.stem for p in (paths.ROOT / "serving" / "ollama").glob("*.Modelfile")]:
            add(Check(f"Ollama model {tag}", tag in listed, "model weights llama-swap serves", "auto"))
    add(Check("terminal entry point (.hermes-home)", (paths.GATEWAY_HOME / "skills" / "ariadne-tasks" / "SKILL.md").exists(),
              "Hermes home with the ariadne-tasks skill and MCP server", "auto"))
    return r


def _server_check(add):
    """Where inference is (our llama-server, a local Ollama, or a LAN box) and whether it answers right now."""
    try:
        from . import serving
        srv = serving.active()
    except Exception as e:
        add(Check("model server", False, f"{type(e).__name__}: {e}", "python -m ariadne server setup", required=False))
        return
    where = f"{srv.get('kind')} {srv.get('url') or '(no url)'}"
    try:
        found = serving.probe(srv, timeout=2)
        add(Check(f"model server: {where}", True,
                  f"answers as {found['kind']}, {len(found.get('models') or [])} model(s)", "", required=False))
    except Exception as e:
        add(Check(f"model server: {where}", False, f"not answering ({e})",
                  "python -m ariadne server setup   (model-free commands still work)", required=False))


def _flow_checks(add):
    """Each approved flow and the tools it declares: a flow that cannot reach its requirements is refused at submit."""
    try:
        from . import flows as flowlib
        approved = flowlib.load_flows()
    except Exception as e:
        add(Check("approved flows", False, f"{type(e).__name__}: {e}", "python -m ariadne flows", required=False))
        return
    for name, fl in approved.items():
        missing = flowlib.missing_requirements(fl)
        needs = ", ".join(fl.requires) or "nothing"
        add(Check(f"flow {name} ({fl.model})", not missing,
                  f"needs {needs}" + (f"; missing: {', '.join(missing)}" if missing else ""),
                  "python -m ariadne install --system", required=False))


def require(full=False):
    """Stop with a clear message if anything required is missing. Called before Ariadne does anything else."""
    r = check(full=full)
    if r.missing:
        sys.exit("Ariadne is missing dependencies:\n" + "\n".join(
            f"  - {c.name}: {c.why}" + (f" (fix: {c.fix})" if c.fix and c.fix != "auto" else "") for c in r.missing)
            + "\nRun:  uv run python -m ariadne install   (add --system to install system tools too)")


# ---------- install ----------

def install(system=False, models=False):
    print(f"Ariadne install on {paths.platform_key()}")
    for name in SYSTEM_TOOLS:
        if not has_tool(name):
            fix = tool_fix(name)
            if system:
                print(f"  installing {name}: {fix}")
                subprocess.run(fix, shell=True, check=False)
            else:
                print(f"  {name} is missing - install it with:  {fix}   (or rerun with --system)")
    if not shutil.which("git") or not shutil.which("uv"):
        sys.exit("git and uv are required before anything else; install them and rerun.")
    print("  Hermes submodule"); subprocess.run(["git", "-C", str(paths.ROOT), "submodule", "update", "--init", "vendor/hermes"], check=True)
    print("  Python env")
    extras = ["--extra", "mcp", "--extra", "ddgs"]   # no messaging extra: Ariadne has no messaging surface
    env = dict(__import__("os").environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(paths.VENV)
    subprocess.run(["uv", "sync", "--project", str(paths.UPSTREAM), "--frozen", "--no-dev", "--python", "3.14", *extras],
                   check=True, env=env)
    subprocess.run(["uv", "pip", "install", "--python", str(paths.VENV_PY), "pytest==9.1.1"], check=True)
    for e in bin_entries():
        if not (bin_dir(e).exists() and any(bin_dir(e).iterdir())) or e["name"].endswith("-rt"):
            print(f"  {e['name']} {e['version']}"); fetch_bin(e)
    if has_tool("ollama"):
        listed = _run(["ollama", "list"]).stdout
        for tag in OLLAMA_MODELS:
            if tag not in listed:
                print(f"  ollama pull {tag}"); subprocess.run(["ollama", "pull", tag], check=True)
        for mf in (paths.ROOT / "serving" / "ollama").glob("*.Modelfile"):
            if mf.stem not in listed:
                subprocess.run(["ollama", "create", mf.stem, "-f", str(mf)], check=True)
    _run_in_venv(["-m", "ariadne", "profile"])
    _run_in_venv(["-m", "ariadne", "flows"])
    if models:  # the catalog defaults (coding, design, writing, image); otherwise each is fetched when a plan picks it
        _run_in_venv(["-m", "ariadne", "models", "install", "--defaults"])
    r = check()
    print(r.text())
    print("\nReady." if not r.missing else f"\nStill missing: {', '.join(c.name for c in r.missing)}")
    return 0 if not r.missing else 1


def _run_in_venv(args):
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(paths.ROOT)
    subprocess.run([str(paths.VENV_PY), *args], check=True, env=env, cwd=str(paths.ROOT))


def doctor():
    r = check()
    print(f"Ariadne doctor ({paths.platform_key()})\n" + r.text())
    if r.missing:
        print(f"\n{len(r.missing)} missing. Run:  uv run python -m ariadne install")
        return 1
    print("\nEverything required is installed.")
    return 0


if __name__ == "__main__":
    print(json.dumps([c.__dict__ for c in check().checks], indent=2))
