"""Ariadne Desktop: the Hermes desktop app, rebranded and locked to the local runtime.

upstream/ is never touched. The app is built from a throwaway shared clone of upstream at the pinned commit
(.ariadne/desktop-src) with desktop/branding.json applied: assets swapped, a few string edits, each with an
exact expected match count, so a Hermes bump that moves one stops the build and names it.

Launch is local-only: the backend is always upstream/ on Ariadne's venv, the app's data lives in its own
folder (no shared state with a stock Hermes install), and the overlay makes a failed local runtime an error
instead of a fall-through to Hermes' installer or remote-gateway setup."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

BRANDING = paths.ROOT / "desktop" / "branding.json"
ASSETS = paths.ROOT / "desktop" / "assets"
SRC = paths.ROOT / ".ariadne" / "desktop-src"
STAMP = SRC / ".ariadne-overlay"


def _python() -> Path:
    return paths.HERMES_EXE.with_name("python.exe" if os.name == "nt" else "python")


def _git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def pin() -> str:
    return subprocess.run(["git", "-C", str(paths.UPSTREAM), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def overlay_hash() -> str:
    import hashlib
    h = hashlib.sha256(BRANDING.read_bytes())
    for p in sorted(ASSETS.iterdir()):
        h.update(p.name.encode() + p.read_bytes())
    return f"{pin()}:{h.hexdigest()[:16]}"


def apply(root: Path, branding: dict) -> list[str]:
    """Apply the overlay to a checkout; raise naming every edit whose match count is off (nothing half-applied)."""
    problems, staged = [], {}
    for e in branding["edits"]:
        f = root / e["file"]
        text = staged.get(f) or (f.read_text(encoding="utf-8") if f.exists() else None)
        if text is None:
            problems.append(f"{e['file']}: file is gone ({e['why']})")
            continue
        n = text.count(e["old"])
        if n != e["count"]:
            problems.append(f"{e['file']}: expected {e['count']} match(es) of {e['old'][:60]!r}, found {n} ({e['why']})")
            continue
        staged[f] = text.replace(e["old"], e["new"])
    for dest in branding["assets"]:
        if not (root / dest).exists():
            problems.append(f"{dest}: upstream asset is gone")
    if problems:
        raise SystemExit("Branding overlay no longer fits this Hermes pin; fix desktop/branding.json:\n  "
                         + "\n  ".join(problems))
    for f, text in staged.items():
        f.write_text(text, encoding="utf-8", newline="")
    for dest, src in branding["assets"].items():
        shutil.copyfile(ASSETS / src, root / dest)
    return [e["file"] for e in branding["edits"]] + list(branding["assets"])


def prepare() -> Path:
    """The branded source tree at the pin (reused while pin and overlay are unchanged; node_modules kept)."""
    rev = pin()
    if not (SRC / ".git").exists():
        SRC.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--shared", "--no-checkout", str(paths.UPSTREAM), str(SRC))
    _git("fetch", "--quiet", str(paths.UPSTREAM), rev, cwd=SRC)
    _git("checkout", "--quiet", "--force", "--detach", rev, cwd=SRC)
    _git("clean", "-fdq", "-e", "node_modules", "-e", "release", "-e", "dist", cwd=SRC)
    apply(SRC, json.loads(BRANDING.read_text(encoding="utf-8")))
    return SRC


def exe() -> Path | None:
    rel = SRC / "apps" / "desktop" / "release"
    for d in ("win-unpacked", "linux-unpacked", "mac", "mac-arm64"):
        for n in ("Hermes.exe", "hermes", "Hermes", "Ariadne.app/Contents/MacOS/Ariadne"):
            if (rel / d / n).is_file():
                return rel / d / n
    return None


def build(force=False) -> Path:
    want = overlay_hash()
    if not force and exe() and STAMP.exists() and STAMP.read_text() == want:
        return exe()
    print("Building Ariadne Desktop (Hermes desktop at the pin + Ariadne branding); first build takes minutes")
    prepare()
    env = {k: v for k, v in os.environ.items() if not k.lower().startswith("npm_")}
    env["HERMES_HOME"] = str(paths.GATEWAY_HOME)
    # Hermes builds the desktop of the checkout its own code lives in, so run the clone's CLI (same pinned
    # Python code, branded apps/desktop) on Ariadne's interpreter: the build lands in the clone, never upstream/.
    env["PYTHONPATH"] = str(SRC)
    r = subprocess.run([str(_python()), "-c", "import sys; from hermes_cli.main import main; sys.argv[0] = 'hermes'; "
                        "sys.exit(main())", "desktop", "--build-only", "--force-build"], env=env, cwd=SRC)
    if r.returncode or not exe():
        raise SystemExit("Ariadne Desktop build failed (see output above)")
    STAMP.write_text(want)
    return exe()


def preflight() -> list[str]:
    """What must hold for a local launch; any miss is reported instead of opening an app that would improvise."""
    miss = []
    if not (paths.UPSTREAM / "hermes_cli").is_dir():
        miss.append(f"Hermes source missing at {paths.UPSTREAM} (git submodule update --init)")
    py = _python()
    if not py.exists():
        miss.append(f"Ariadne's Python missing at {py} (python -m ariadne install)")
    elif subprocess.run([str(py), "-c", "import hermes_cli"], capture_output=True).returncode:
        miss.append(f"{py} cannot import Hermes (python -m ariadne install)")
    if not shutil.which("node"):
        miss.append("Node.js missing (python -m ariadne install --system)")
    return miss


def launch_env(cwd: str) -> dict:
    """Hermes' own launcher env (so its knobs keep working), then Ariadne's locks on top."""
    sys.path.insert(0, str(paths.UPSTREAM))
    from hermes_cli.main_desktop import _desktop_launch_env  # upstream's launcher logic, used as-is
    env, _flags = _desktop_launch_env(argparse.Namespace(hermes_root=str(paths.UPSTREAM), cwd=cwd))
    env = {k: v for k, v in env.items() if not k.lower().startswith("npm_")}
    branding = json.loads(BRANDING.read_text(encoding="utf-8"))
    env.update(branding["env"])
    env.update({
        "HERMES_HOME": str(paths.GATEWAY_HOME),
        "HERMES_DESKTOP_HERMES_ROOT": str(paths.UPSTREAM),
        "HERMES_DESKTOP_PYTHON": str(_python()),
        # The app's own state (window, saved connections) in the repo: never shared with a stock Hermes install,
        # and the same folder whichever shell launched it (APPDATA can be virtualized for sandboxed launchers).
        "HERMES_DESKTOP_USER_DATA_DIR": str(paths.ROOT / ".ariadne" / "desktop-data"),
    })
    for k in ("HERMES_DESKTOP_REMOTE_URL", "HERMES_DESKTOP_REMOTE_TOKEN", "HERMES_DESKTOP_IGNORE_EXISTING"):
        env.pop(k, None)
    return env


def launch(cwd: str, rebuild=False) -> int:
    miss = preflight()
    if miss:
        print("Ariadne Desktop runs only on the local runtime, and it is not ready:\n  " + "\n  ".join(miss))
        return 1
    app = build(force=rebuild)
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(app)], env=launch_env(cwd), cwd=cwd, creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    print(f"Ariadne Desktop: local runtime {paths.UPSTREAM} on {paths.GATEWAY_HOME}, workspace {cwd}")
    return 0
