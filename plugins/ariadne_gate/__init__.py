"""Ariadne gate - Hermes plugin for the chat home.

The chat may talk and submit tasks; every tool that would do the work is refused with the drill's instruction.
Attempts are recorded in <HERMES_HOME>/logs/ariadne_gate.jsonl.
"""
import logging

from . import gate

logger = logging.getLogger(__name__)


def register(ctx):
    ctx.register_hook("pre_tool_call", gate.pre_tool_call)
    logger.info("Ariadne gate active: the chat home cannot do the work itself")
