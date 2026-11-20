"""The tools a runtime turn may call: files, search, a terminal - and nothing it was not offered.

Every path goes through `_path`, so a tool cannot read or write outside the workspace it was given (the flows already
say "absolute paths inside your workspace"; this is the code that makes it true). Output is truncated: a tool result
is context the model pays for, not a log. The plan phase gets `READ_ONLY` only, which is what makes "nothing changes
before sign-off" a property of the loop rather than a promise in a prompt.
"""
import re
import subprocess
from pathlib import Path

MAX_OUTPUT = 8000
READ_ONLY = ("read_file", "search_files", "list_dir")


class ToolError(RuntimeError):
    pass


def _cut(text: str, limit: int = MAX_OUTPUT) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + f"\n[... {len(text) - limit} more characters]"


def _path(ws, p) -> Path:
    ws = Path(ws).resolve()
    q = Path(p or ".")
    target = (ws / q) if not q.is_absolute() else q
    r = target.resolve()
    if r != ws and ws not in r.parents:
        raise ToolError(f"{p} is outside the workspace ({ws})")
    return r


def read_file(ws, path, offset=1, limit=400):
    p = _path(ws, path)
    if not p.exists():
        raise ToolError(f"no such file: {path}")
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(offset))
    end = min(len(lines), start - 1 + max(1, min(int(limit), 2000)))
    body = "\n".join(f"{i}|{lines[i - 1]}" for i in range(start, end + 1))
    more = f"\n[... {len(lines) - end} more lines]" if end < len(lines) else ""
    return _cut(f"{p} ({len(lines)} lines, showing {start}-{end})\n{body}{more}")


def write_file(ws, path, content):
    p = _path(ws, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content or "", encoding="utf-8")
    return f"wrote {p} ({p.stat().st_size} bytes)"


def patch_file(ws, path, old, new, replace_all=False):
    p = _path(ws, path)
    if not p.exists():
        raise ToolError(f"no such file: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")
    n = text.count(old)
    if not n:
        raise ToolError(f"that text is not in {path}; read the file again")
    if n > 1 and not replace_all:
        raise ToolError(f"that text appears {n} times in {path}; give more context or replace_all=true")
    text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    return f"patched {p} ({n if replace_all else 1} occurrence(s))"


def search_files(ws, pattern, path=".", glob=None, limit=50):
    base = _path(ws, path)
    rx = re.compile(pattern, re.I)
    hits, files = [], sorted(base.rglob(glob or "*")) if base.is_dir() else [base]
    for f in files:
        if not f.is_file() or f.stat().st_size > 2_000_000:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(Path(ws).resolve()).as_posix()}:{i}: {line.strip()[:200]}")
                    if len(hits) >= max(1, min(int(limit), 500)):
                        return _cut("\n".join(hits) + "\n[limit reached]")
        except OSError:
            continue
    return _cut("\n".join(hits)) or f"no match for {pattern!r}"


def list_dir(ws, path=".", depth=2):
    base = _path(ws, path)
    if not base.is_dir():
        raise ToolError(f"not a directory: {path}")
    root = Path(ws).resolve()
    out = []
    for p in sorted(base.rglob("*")):
        if len(p.relative_to(base).parts) > max(1, min(int(depth), 6)):
            continue
        rel = p.relative_to(root).as_posix()
        out.append(rel + ("/" if p.is_dir() else f"  ({p.stat().st_size} B)"))
        if len(out) > 400:
            out.append("[... more; narrow the path]")
            break
    return _cut("\n".join(out)) or "(empty)"


def terminal(ws, command, timeout=180):
    try:
        p = subprocess.run(command, shell=True, cwd=str(Path(ws).resolve()), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=max(1, min(int(timeout), 1800)))
    except subprocess.TimeoutExpired:
        raise ToolError(f"the command did not finish within {timeout}s")
    out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if (p.stderr or "").strip() else "")
    return _cut(f"exit {p.returncode}\n{out or '(no output)'}")


TOOLS = {"read_file": read_file, "write_file": write_file, "patch_file": patch_file, "search_files": search_files,
         "list_dir": list_dir, "terminal": terminal}

SCHEMAS = [
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a text file from the workspace, with line numbers.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Write a whole file into the workspace (creates directories).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "patch_file", "description": "Replace one piece of text in a file. The old text must be unique "
                                            "unless replace_all is true.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
            "replace_all": {"type": "boolean"}}, "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {
        "name": "search_files", "description": "Regex search inside the workspace; returns file:line: text.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"},
            "limit": {"type": "integer"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "list_dir", "description": "List files under a workspace directory.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "depth": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "terminal", "description": "Run a shell command in the workspace and return its exit code and output.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}},
                       "required": ["command"]}}},
]

SCHEMA_BY_NAME = {s["function"]["name"]: s for s in SCHEMAS}


def offered(phase: str):
    """The tool schemas a phase may use: the plan phase gets the read-only ones and nothing else."""
    if (phase or "").split(":")[0] in ("plan", "review", "checkpoint", "learn"):
        return [SCHEMA_BY_NAME[n] for n in READ_ONLY]
    return list(SCHEMAS)


def call(name, arguments, ws, phase="execute"):
    """Run one tool call. Never raises: a refusal or a failure is a tool result the model can read and recover from."""
    if name not in TOOLS:
        return f"ERROR: there is no tool {name!r}; available: {', '.join(sorted(TOOLS))}"
    if name not in [s["function"]["name"] for s in offered(phase)]:
        return f"ERROR: {name} is not available in the {phase} phase; this phase is read-only"
    if "__bad_arguments__" in (arguments or {}):
        return f"ERROR: the tool arguments were not valid JSON: {arguments['__bad_arguments__']}"
    try:
        return TOOLS[name](ws, **(arguments or {}))
    except ToolError as e:
        return f"ERROR: {e}"
    except TypeError as e:
        return f"ERROR: bad arguments for {name}: {e}"
    except Exception as e:
        return f"ERROR: {name} failed: {type(e).__name__}: {e}"
