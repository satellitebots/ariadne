"""What a worker may do without asking: permissions.yaml (default: everything).

Hermes ships with an approval layer and a stack of guards meant for agents driven by hosted models. Ariadne runs
local models on the person's own machine, so all of them are switched off (flows.BASE_CONFIG, HERMES_ENV and the
interpreter overlay tools/permissions_hook.py). What is left is this file's rules:

  ask   the run stops and waits (needs you) until `approve` (yes, for the rest of the run) or `reject` (no, and why)
  deny  refused outright

Rules cover `tools` (a step's toolsets or MCP servers, checked before the step starts), `commands` (regexes on
terminal commands) and `paths` (globs on file writes). Commands and paths are checked inside the Hermes process by
the overlay, which writes the question to `.ariadne/asks/<run>.json`; the engine sees it, stops the step at its next
boundary and holds the run until the question is answered.
"""
import fnmatch
import json
import os
import re
import time
from pathlib import Path

from . import paths, yamlio

FILE = Path(os.environ.get("ARIADNE_PERMISSIONS") or paths.ROOT / "permissions.yaml")
ASKS = paths.STATE / "asks"
KINDS = ("tools", "commands", "paths")
HOOK = paths.ROOT / "tools" / "permissions_hook.py"

# Set on every Hermes run: the read-before-write guard and the approval layer go away entirely.
HERMES_ENV = {"HERMES_DISABLE_FILE_STATE_GUARD": "1", "HERMES_YOLO_MODE": "1",
              "HERMES_AUTO_CONTINUE_FRESHNESS": "0.001"}   # its gateway never continues a session on its own


def load(file=None) -> dict:
    """The rules, normalised: {"ask": {kind: [..]}, "deny": {kind: [..]}}. A missing file means allow everything."""
    file = Path(file or FILE)
    raw = {}
    if file.exists():
        raw = yamlio.safe_load(file.read_text(encoding="utf-8")) or {}
    if str(raw.get("default", "allow")).lower() != "allow":
        raise ValueError(f"{file}: default must be 'allow' (list what should ask under ask:)")
    out = {}
    for mode in ("ask", "deny"):
        sect = raw.get(mode) or {}
        out[mode] = {k: [str(x) for x in (sect.get(k) or [])] for k in KINDS}
        for pat in out[mode]["commands"]:
            re.compile(pat)
    return out


def _norm(p: str) -> str:
    return os.path.normcase(os.path.expanduser(str(p))).replace("\\", "/")


def match(rules, kind, value) -> tuple[str, str] | None:
    """("deny" | "ask", the rule) for the first rule that matches value, deny first; None when allowed."""
    for mode in ("deny", "ask"):
        for rule in rules[mode][kind]:
            if kind == "commands" and re.search(rule, value):
                return mode, rule
            if kind == "paths" and fnmatch.fnmatch(_norm(value), _norm(rule)):
                return mode, rule
            if kind == "tools" and value == rule:
                return mode, rule
    return None


# ---------- questions and answers, per run (shared with the overlay through files) ----------

def _pending_file(rid):
    return ASKS / f"{rid}.json"


def _approved_file(rid):
    return ASKS / f"{rid}.approved.json"


def pending(rid) -> dict | None:
    try:
        return json.loads(_pending_file(rid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def approved(rid) -> list:
    try:
        return json.loads(_approved_file(rid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def is_approved(rid, kind, rule) -> bool:
    return any(a["kind"] == kind and a["rule"] == rule for a in approved(rid))


def ask(rid, kind, what, rule) -> dict:
    ASKS.mkdir(parents=True, exist_ok=True)
    q = {"kind": kind, "what": what, "rule": rule, "asked": time.time()}
    _pending_file(rid).write_text(json.dumps(q), encoding="utf-8")
    return q


def answer(rid, yes: bool) -> dict | None:
    """Close the open question: a yes is remembered for the rest of the run. Returns the question."""
    q = pending(rid)
    if not q:
        return None
    if yes:
        got = approved(rid) + [{"kind": q["kind"], "rule": q["rule"], "at": time.time()}]
        _approved_file(rid).write_text(json.dumps(got), encoding="utf-8")
    for _ in range(20):
        try:
            _pending_file(rid).unlink()
            break
        except FileNotFoundError:
            break
        except OSError:
            time.sleep(0.05)
    return q


def describe(q) -> str:
    noun = {"tools": "use", "commands": "run", "paths": "write"}[q["kind"]]
    return f"wants to {noun} {q['what']} (permissions.yaml ask: {q['rule']})"


# ---------- the overlay ----------

def install_hook():
    """Make sure every Python process in the venv loads the overlay (inert unless ARIADNE_PERMISSIONS_RUN is set)."""
    if paths.WINDOWS:
        site = paths.VENV / "Lib" / "site-packages"
    else:
        found = sorted((paths.VENV / "lib").glob("python*/site-packages"))
        site = found[-1] if found else None
    if site is None or not site.exists():
        return None
    pth = site / "ariadne_permissions.pth"
    line = f"import sys; sys.path.append(r'{HOOK.parent}'); import permissions_hook\n"
    if not pth.exists() or pth.read_text(encoding="utf-8") != line:
        pth.write_text(line, encoding="utf-8")
    return pth


def hermes_env(rid) -> dict:
    """Environment for one Hermes run of `rid`: guards off, the overlay on with this run's rules."""
    return dict(HERMES_ENV, ARIADNE_PERMISSIONS_RUN=rid, ARIADNE_PERMISSIONS=str(FILE), ARIADNE_STATE=str(paths.STATE))
