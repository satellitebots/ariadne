"""What changed in a task's workspace, for people who need to see the work.

The desktop app and the terminal both need the answer to "what did it actually produce?", and neither can see
inside the worker's Hermes home. The workspace is the artefact: git already knows which files moved, so ask it.
Read-only, no model, and safe to call while a task is running.
"""
import os
import subprocess


def changes(ws: str) -> dict:
    """`git status` and a diffstat for a workspace. Never raises: the note says why when there is nothing to show."""
    out = {"workspace": ws, "git": False, "files": [], "stat": "", "note": ""}
    if not ws or not os.path.isdir(ws):
        out["note"] = "workspace not found"
        return out
    try:
        top = subprocess.run(["git", "-C", ws, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=10)
        if top.returncode != 0:
            out["note"] = "the workspace is not a git repository"
            return out
        out["git"] = True
        st = subprocess.run(["git", "-C", ws, "status", "--porcelain"], capture_output=True, text=True, timeout=10)
        out["files"] = [line for line in st.stdout.splitlines() if line.strip()][:200]
        ds = subprocess.run(["git", "-C", ws, "diff", "HEAD", "--stat"], capture_output=True, text=True, timeout=20)
        if ds.returncode != 0:   # a repository with no commits yet
            ds = subprocess.run(["git", "-C", ws, "diff", "--stat"], capture_output=True, text=True, timeout=20)
        out["stat"] = ds.stdout.strip()[-4000:]
    except (OSError, subprocess.SubprocessError) as e:
        out["note"] = str(e)
    return out
