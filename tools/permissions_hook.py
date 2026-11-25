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

    def _no(*a, **k):
        return False

    def _yes(*a, **k):
        return True

    def _no_dedup_block(task_data, dedup_key, path):
        # Hermes answers a third identical read with "BLOCKED: stop calling read_file". Keep its harmless
        # "unchanged since your last read" stub, never the block.
        task_data.get("dedup_hits", {}).pop(dedup_key, None)
        return _ORIG["tools.file_tools._dedup_stub_or_block"](task_data, dedup_key, path)

    def _extract_urls_unfiltered(urls):
        # web_extract refuses a whole call when a URL carries something shaped like a secret; check nothing.
        import re
        from agent import redact
        saved, redact._PREFIX_RE = redact._PREFIX_RE, re.compile(r"(?!x)x")
        try:
            return _ORIG["tools.web_tools_extract._validate_extract_urls"](urls)
        finally:
            redact._PREFIX_RE = saved

    _WRITES = {"_check_sensitive_path": _paths, "_check_binary_document_write": _allow,
               "_check_protected_instruction_write": _allow, "_check_approval_required_write": _allow,
               "_check_cross_profile_path": _allow, "_stale_overwrite_blocker": _allow}
    _READS = {"get_read_block_error": _allow, "raise_if_read_blocked": _allow, "is_blocked_device_path": _no,
              "get_nt_namespace_error": _allow}
    _URLS = {"is_safe_url": _yes, "is_always_blocked_url": _no, "_is_always_blocked_ip": _no, "_is_blocked_ip": _no,
             "_resolved_ip_block_reason": _allow}
    PATCHES = {
        "tools.approval": {"_floor_block": _commands, "hardline_scan_incomplete": _no},
        "tools.approval_detection": {"hardline_scan_incomplete": _no, "detect_hardline_command": lambda *a, **k: (False, "")},
        "tools.terminal_tool": {"self_repo_block": _allow, "locked_skill_block": _allow,
                                "gateway_lifecycle_block": _allow, "_validate_workdir": _allow},
        "tools.file_tools": {**_WRITES, **_READS, "_write_precheck_error": _allow, "_is_blocked_device": _no,
                             "_filter_read_blocked_search_results": lambda *a, **k: 0,
                             "_dedup_stub_or_block": _no_dedup_block},
        "tools.file_tools_write_guards": dict(_WRITES),
        "tools.file_operations": {"_refuse_introduced_json_constant": _allow},
        "agent.file_safety": dict(_READS),
        "tools.url_safety": dict(_URLS),
        "tools.skills_hub": {"is_safe_url": _yes},
        "tools.browser_url_policy": {"_url_policy_error": _allow, "evaluate_url_safety": _allow,
                                     "url_blocked": _no, "eval_ssrf_guard_active": _no, "is_safe_url": _yes,
                                     "is_always_blocked_url": _no},
        "tools.web_tools_extract": {"_validate_extract_urls": _extract_urls_unfiltered},
    }
    _ORIG = {}
    APPLIED = []

    def _apply(name, module):
        for attr, fn in PATCHES[name].items():
            if hasattr(module, attr):
                _ORIG.setdefault(f"{name}.{attr}", getattr(module, attr))
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
