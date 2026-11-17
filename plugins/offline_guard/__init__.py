"""Ariadne offline guard - Hermes plugin.

Defense in depth for a local-only harness (config already closes all known egress, see WORKLOG A2):
- socket guard: refuses non-local DNS lookups and connects in every Hermes process that loads plugins
- pre_tool_call policy: refuses web/browser tools and commands that would reach a non-local host
Blocked attempts are appended to <HERMES_HOME>/logs/offline_guard.jsonl.
"""
import logging
import os
from pathlib import Path

from . import guard, policy

logger = logging.getLogger(__name__)


def _log_path():
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    logs = Path(home) / "logs"
    try:
        logs.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return str(logs / "offline_guard.jsonl")


def register(ctx):
    mode = guard.install(log_path=_log_path())
    ctx.register_hook("pre_tool_call", policy.pre_tool_call)
    logger.info("Ariadne offline guard active (mode=%s, pid=%s)", mode, os.getpid())
