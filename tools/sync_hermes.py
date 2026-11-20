"""Bump the pinned Hermes submodule and rebuild the venv from its lockfile.

    python tools/sync_hermes.py                 # re-checkout the recorded pin and resync
    python tools/sync_hermes.py --to v0.24.0    # move to a tag, branch or commit
    python tools/sync_hermes.py --dry-run       # print the commands, change nothing

The submodule is pristine: we never edit inside it, so `git add vendor/hermes` is the whole pin bump and a merge never
happens. After it runs, `pytest -q` is the acceptance: the contract tests name any CLI flag, config key or hook that
moved, and `worker.hermes_run` is the only adapter that should need a fix.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERMES = ROOT / "vendor" / "hermes"


def _run(cmd, dry=False):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    if dry:
        return 0
    return subprocess.run([str(c) for c in cmd], cwd=str(ROOT)).returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", default="", help="a tag, branch or commit in the submodule; empty keeps the pin")
    ap.add_argument("--no-sync", action="store_true", help="bump the pointer but do not rebuild the venv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not (HERMES / ".git").exists():
        print(f"{HERMES} is not a git checkout; run `git submodule update --init vendor/hermes` first", file=sys.stderr)
        return 2
    steps = [["git", "-C", HERMES, "fetch", "--tags", "origin"]]
    if a.to:
        steps.append(["git", "-C", HERMES, "checkout", a.to])
    steps.append(["git", "-C", ROOT, "add", "vendor/hermes"])
    if not a.no_sync:
        steps.append(["uv", "sync", "--project", HERMES, "--frozen", "--python", "3.14",
                      "--extra", "mcp", "--extra", "ddgs"])
    for cmd in steps:
        code = _run(cmd, a.dry_run)
        if code:
            return code
    if not a.dry_run:
        head = subprocess.run(["git", "-C", HERMES, "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
        print(f"\npin: {head.stdout.strip()}  (staged; commit when the suite is green: pytest -q)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
