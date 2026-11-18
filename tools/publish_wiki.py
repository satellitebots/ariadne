"""Publish wiki/ to the GitHub wiki (satellitebots/ariadne.wiki), rewriting links for it.

In the repo, wiki pages link each other as `Page.md` and the rest of the repo as `../path`. On the GitHub wiki,
pages are `Page` and repo files need full URLs.

    python tools/publish_wiki.py [--dry-run]
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "wiki"
CLONE = ROOT / ".ariadne" / "wiki-repo"
REMOTE = "https://github.com/satellitebots/ariadne.wiki.git"
BLOB = "https://github.com/satellitebots/ariadne/blob/main/"
TREE = "https://github.com/satellitebots/ariadne/tree/main/"
RAW = "https://raw.githubusercontent.com/satellitebots/ariadne/main/"
LINK = re.compile(r"(!?)\]\(([^)\s]+)\)")


def rewrite(text):
    def fix(m):
        bang, target = m.groups()
        if re.match(r"^[a-z]+:", target):
            return m.group(0)
        path, _, anchor = target.partition("#")
        anchor = "#" + anchor if anchor else ""
        if path.startswith("../"):
            rel = path[3:]
            base = RAW if bang else (TREE if rel.endswith("/") else BLOB)
            return f"{bang}]({base}{rel}{anchor})"
        if path.endswith(".md"):
            return f"{bang}]({path[:-3]}{anchor})"
        return m.group(0)
    return LINK.sub(fix, text)


def git(*args):
    subprocess.run(["git", "-C", str(CLONE), *args], check=True)


def main(argv):
    if CLONE.exists():
        git("fetch", "-q", "origin")
        git("reset", "-q", "--hard", "origin/HEAD")
    else:
        subprocess.run(["git", "clone", "-q", REMOTE, str(CLONE)], check=True)
    for old in CLONE.glob("*.md"):
        old.unlink()
    for page in SRC.glob("*.md"):
        (CLONE / page.name).write_text(rewrite(page.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    git("add", "-A")
    if subprocess.run(["git", "-C", str(CLONE), "diff", "--cached", "--quiet"]).returncode == 0:
        print("wiki already up to date")
        return 0
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    git("commit", "-q", "-m", f"Sync from wiki/ at {head.stdout.strip()}")
    if "--dry-run" not in argv:
        git("push", "-q", "origin", "HEAD")
    print("published" if "--dry-run" not in argv else "committed locally (dry run)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
