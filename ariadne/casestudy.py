"""Publish a case-study workspace into the repo: case_study/projects/<name>/.

Only what the workspace's own git tracks at HEAD is copied (git archive), so scratch scripts, caches, corpora and
indexes stay out. A workspace with no commits (a design folder) is copied as is, minus anything git would ignore.

    python -m ariadne casestudy export <workspace> <name>
"""
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from . import paths

PROJECTS = paths.ROOT / "case_study" / "projects"
SKIP = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", ".mypy_cache", ".ruff_cache"}


def _git(ws, *args):
    return subprocess.run(["git", "-C", str(ws), *args], capture_output=True)


def export(workspace, name):
    ws, dest = Path(workspace).resolve(), PROJECTS / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    head = _git(ws, "rev-parse", "--short", "HEAD")
    if head.returncode == 0:
        tar = _git(ws, "archive", "--format=tar", "HEAD")
        with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
            t.extractall(dest, filter="data")
        source = f"commit {head.stdout.decode().strip()}"
        # Work the model left uncommitted (a run stopped mid-step) is part of the story: tracked files are taken as
        # they are in the working tree. Untracked files (scratch scripts, indexes) still stay out.
        changed = [ln[3:].strip() for ln in _git(ws, "status", "--porcelain").stdout.decode().splitlines()
                   if ln[:2].strip() in ("M", "MM", "AM") or ln[1:2] == "M"]
        for rel in changed:
            src = ws / rel
            if src.is_file():
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / rel)
        if changed:
            source += f" + uncommitted changes to {', '.join(changed)}"
    else:
        for p in ws.rglob("*"):
            if p.is_file() and not (SKIP & set(p.relative_to(ws).parts)):
                if _git(ws, "check-ignore", "-q", str(p)).returncode == 0:
                    continue
                out = dest / p.relative_to(ws)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, out)
        source = "uncommitted workspace (no commits)"
    files = sorted(str(p.relative_to(dest)).replace("\\", "/") for p in dest.rglob("*") if p.is_file())
    (dest / ".snapshot.json").write_text(json.dumps(
        {"name": name, "source": source, "exported": time.strftime("%Y-%m-%d %H:%M"), "files": len(files)},
        indent=2), encoding="utf-8")
    return dest, source, len(files)


def main(argv):
    if len(argv) != 3 or argv[0] != "export":
        print(__doc__)
        return 2
    dest, source, n = export(argv[1], argv[2])
    print(f"{n} files from {source} -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
