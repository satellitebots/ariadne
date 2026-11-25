"""Lift Hermes's guards inside a worker's Hermes process; enforce only permissions.yaml (ariadne/permissions.py).

Loaded at interpreter start by .venv site-packages ariadne_permissions.pth (written by permissions.install_hook).
Inert unless ARIADNE_PERMISSIONS_RUN is set, which the engine does for each worker run. vendor/hermes is never
edited: a meta-path finder lets each Hermes module load as shipped, then swaps the guard functions below.

Config and environment switch off the approval layer, loop hard stops, private-URL block and read-before-write guard
(flows.BASE_CONFIG, permissions.HERMES_ENV). What config cannot reach and this overlay replaces:
  tools.approval       _floor_block (hardline blocklist, runtime self-delete, sudo -S guard, approvals.deny)
                       -> permissions.yaml command rules; hardline_scan_incomplete -> never
  tools.terminal_tool  self_repo_block, locked_skill_block, gateway_lifecycle_block -> allow
  tools.file_tools     _check_sensitive_path -> permissions.yaml path rules; binary-document, protected-instruction,
                       approval-required, cross-profile and stale-overwrite write guards -> allow
"""
import os
import sys

RUN = os.environ.get("ARIADNE_PERMISSIONS_RUN")

if RUN:
    import importlib.abc

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _state = {}

    def _perm():
        # Imported on first use, after Hermes's own `tools` package is loaded, so the repo root never shadows it.
        if _ROOT not in sys.path:
            sys.path.append(_ROOT)
        from ariadne import permissions
        return permissions

    def check(kind, value):
        """None when allowed; otherwise the text the worker gets back instead of the action."""
        p = _perm()
        if "rules" not in _state:
            _state["rules"] = p.load()
        hit = p.match(_state["rules"], kind, str(value))
        if not hit:
            return None
        mode, rule = hit
        if mode == "deny":
            return (f"BLOCKED: the person forbids this (permissions.yaml deny: {rule}). Do not retry or rephrase it; "
                    "do the work another way, or report that it cannot be done.")
        if p.is_approved(RUN, kind, rule):
            return None
        p.ask(RUN, kind, str(value)[:500], rule)
        return (f"WAITING FOR THE PERSON: this needs their OK first (permissions.yaml ask: {rule}). The run pauses "
                "here. Make no further tool calls; you will be told the answer when it resumes.")

    def _commands(command, *a, **k):
        msg = check("commands", command)
        return None if msg is None else {"approved": False, "user_deny": True, "message": msg}

    def _paths(filepath, *a, **k):
        return check("paths", filepath)

    def _allow(*a, **k):
        return None

    _WRITES = {"_check_sensitive_path": _paths, "_check_binary_document_write": _allow,
               "_check_protected_instruction_write": _allow, "_check_approval_required_write": _allow,
               "_check_cross_profile_path": _allow, "_stale_overwrite_blocker": _allow}
    PATCHES = {
        "tools.approval": {"_floor_block": _commands, "hardline_scan_incomplete": lambda *a, **k: False},
        "tools.approval_detection": {"hardline_scan_incomplete": lambda *a, **k: False,
                                     "detect_hardline_command": lambda *a, **k: (False, "")},
        "tools.terminal_tool": {"self_repo_block": _allow, "locked_skill_block": _allow,
                                "gateway_lifecycle_block": _allow},
        "tools.file_tools": dict(_WRITES),
        "tools.file_tools_write_guards": dict(_WRITES),
    }
    APPLIED = []

    def _apply(name, module):
        for attr, fn in PATCHES[name].items():
            if hasattr(module, attr):
                setattr(module, attr, fn)
                APPLIED.append(f"{name}.{attr}")

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name not in PATCHES:
                return None
            for finder in sys.meta_path:
                if finder is self or not hasattr(finder, "find_spec"):
                    continue
                spec = finder.find_spec(name, path, target)
                if spec is not None:
                    break
            else:
                return None
            loader = spec.loader
            original = loader.exec_module

            def exec_module(module):
                original(module)
                _apply(name, module)
            loader.exec_module = exec_module
            return spec

    for _name in PATCHES:
        if _name in sys.modules:
            _apply(_name, sys.modules[_name])
    sys.meta_path.insert(0, _Finder())
