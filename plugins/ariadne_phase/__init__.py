"""Ariadne phase guard - Hermes plugin, installed into each flow's worker home by ariadne.flows.

The orchestrator runs every task twice: a plan run (before sign-off) and an execute run (after). It writes the
current phase to <HERMES_HOME>/ariadne_phase before each run. In the plan phase only the flow's plan_tools
(read-only: read files, search, recall memory, git status/diff/log) may run; anything else is refused with a
message telling the model to put it in the plan instead. Every tool call is appended to
<HERMES_HOME>/logs/ariadne_tools.jsonl so a run can be audited.
"""
from . import phase


def register(ctx):
    ctx.register_hook("pre_tool_call", phase.pre_tool_call)
