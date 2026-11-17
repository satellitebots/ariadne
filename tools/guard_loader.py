"""Start the Ariadne offline guard at interpreter start (loaded by .venv ariadne_offline_guard.pth).

Inert unless ARIADNE_GUARD_ALL_PROCS=1. Covers every Python process of Ariadne's venv, including the
Hermes CLI, which does not load plugins (only the gateway does). Blocks go to
<HERMES_HOME>/logs/offline_guard.jsonl, the same file the plugin writes.
"""
import os
import sys

if os.environ.get("ARIADNE_GUARD_ALL_PROCS") == "1":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins"))
    from offline_guard import guard as _guard

    _home = os.environ.get("HERMES_HOME")
    _log = None
    if _home:
        os.makedirs(os.path.join(_home, "logs"), exist_ok=True)
        _log = os.path.join(_home, "logs", "offline_guard.jsonl")
    _guard.install(log_path=_log)
