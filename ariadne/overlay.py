"""Root-level overrides over the pinned Hermes checkout (`vendor/hermes`).

Hermes stays a pristine submodule: a pin bump is a pointer change, and nothing inside it is edited. When Ariadne needs
to own one of its modules, the file goes in `overlay/<package>/<module>.py`, and the package's `__path__` is prepended
with `overlay/<package>` at bootstrap - so our file wins for that module while every other module still comes from the
submodule. That is the "runtime gut" applied to code: we own the few modules we must, and the rest keeps arriving with
their upgrades.

`overlay.yaml` is the ledger. Every override names why it exists and the test that proves it, so an upstream rename
shows up as a missing file instead of a silently dead shadow.

Import order, once `install()` has run: repo root, then `vendor/hermes`, then site-packages.
"""
import importlib
import sys
from pathlib import Path

from . import paths, yamlio

OVERLAY = paths.ROOT / "overlay"
MANIFEST = paths.ROOT / "overlay.yaml"


def install(root=None, hermes=None):
    """Put the repo root and the pinned checkout ahead of site-packages, once. Idempotent; returns the order."""
    order = [str(root or paths.ROOT), str(hermes or paths.UPSTREAM)]
    for p in order:
        while p in sys.path:
            sys.path.remove(p)
    sys.path[0:0] = order
    return order


def extend(package, overlay_dir=None):
    """Prepend `overlay/<package>` to an imported package's `__path__`, so our modules win per file."""
    d = Path(overlay_dir or OVERLAY) / package
    if not d.is_dir():
        return False
    pkg = importlib.import_module(package)
    path = str(d)
    if path in pkg.__path__:
        pkg.__path__.remove(path)
    pkg.__path__.insert(0, path)
    return True


def apply(overlay_dir=None, hermes=None):
    """Install the import order, then extend every package that has an overlay directory. Returns the names applied."""
    install(hermes=hermes)
    base = Path(overlay_dir or OVERLAY)
    applied = []
    for d in sorted(base.glob("*")) if base.is_dir() else []:
        if d.is_dir() and extend(d.name, base):
            applied.append(d.name)
    return applied


def manifest(path=None):
    """The declared overrides: [{module, why, test}]. Empty is a valid ledger."""
    p = Path(path or MANIFEST)
    if not p.exists():
        return []
    data = yamlio.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("overrides") or []


def check(path=None, overlay_dir=None):
    """Problems with the ledger: a declared module with no file, or an override with no reason/test."""
    base = Path(overlay_dir or OVERLAY)
    problems = []
    for row in manifest(path):
        module = str(row.get("module") or "").strip()
        if not module:
            problems.append("an override has no module")
            continue
        f = base / (module.replace(".", "/") + ".py")
        if not f.exists():
            try:
                shown = f.relative_to(paths.ROOT).as_posix()
            except ValueError:                      # a temporary overlay in a test
                shown = str(f)
            problems.append(f"{module}: no file at {shown}")
        if not str(row.get("why") or "").strip():
            problems.append(f"{module}: no reason recorded")
        if not str(row.get("test") or "").strip():
            problems.append(f"{module}: no test named")
    return problems
