"""MCP server: a small Git toolset for Hermes workers (stdio). Run: python -m ariadne.git_mcp

Local operations only (no clone/fetch/pull/push). Commits use the repository's own git identity and add no
trailers: the user owns the changes."""
import subprocess

from mcp.server.mcpserver import MCPServer

server = MCPServer("ariadne-git", instructions="Local Git operations on a repository path.")
MAX = 20000


def _git(repo, *args):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    out = (p.stdout + (("\n" + p.stderr) if p.stderr.strip() else "")).strip()
    if len(out) > MAX:
        out = out[:MAX] + f"\n... (truncated, {len(out)} chars)"
    return out if p.returncode == 0 else f"git {args[0]} failed (exit {p.returncode}):\n{out}"


from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "git")

@server.tool()
def git_status(repo: str) -> str:
    """Short status of the working tree (branch, changed and untracked files)."""
    return _git(repo, "status", "--short", "--branch") or "clean"


@server.tool()
def git_diff(repo: str, staged: bool = False, path: str = "") -> str:
    """Diff of unstaged changes (or staged, if staged=true), optionally for one path."""
    args = ["diff"] + (["--cached"] if staged else []) + (["--", path] if path else [])
    return _git(repo, *args) or "no differences"


@server.tool()
def git_log(repo: str, count: int = 10) -> str:
    """Recent commits, one per line."""
    return _git(repo, "log", f"-{max(1, min(int(count), 100))}", "--oneline", "--decorate")


@server.tool()
def git_show(repo: str, ref: str = "HEAD") -> str:
    """One commit with its diff."""
    return _git(repo, "show", "--stat", "--patch", ref)


@server.tool()
def git_add(repo: str, paths: str = ".") -> str:
    """Stage files. paths: space-separated paths, '.' for everything."""
    return _git(repo, "add", "--", *paths.split()) or "staged"


@server.tool()
def git_commit(repo: str, message: str) -> str:
    """Commit what is staged, with the repository's configured author. No trailers are added."""
    return _git(repo, "commit", "-m", message)


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
