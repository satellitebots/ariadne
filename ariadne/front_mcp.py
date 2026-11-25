"""The MCP front: every verb in `verbs.VERBS` as an MCP tool, generated, never hand-written (docs/DESIGN.md).

An outside agent (Claude, another MCP client) gets the same verbs as the UI and the chat, plus the bypass: `define`
hands in a whole task definition, so the local orchestrator never loads, and `run_logs` / `events` give the extra
control a capable agent needs. Calling any tool makes sure the worker process is running.

    python -m ariadne.front_mcp          # stdio
"""
import inspect

from mcp.server.mcpserver import MCPServer

from . import verbs

INSTRUCTIONS = """Ariadne runs durable tasks on local models. A task is a signed definition: a flow (template), a
workspace, steps (each with tools, outputs and a check), task gates, and a trigger (manual, now, at a time, or cron).
A run is one execution of a signed version; workers do one step each, and one machine is shared through a lease.

Define a task either by talking to the local orchestrator (draft, then say) or directly with define(yaml) - see
flows for each template's parameters and steps. The person signs (sign); you show them the definition first. Then
run, follow with run_show, and steer: park_run, steer, resume. machine says who holds the GPU."""

server = MCPServer("ariadne", instructions=INSTRUCTIONS)


def _expose(v):
    def tool(**kwargs):
        from .daemon import ensure_worker
        try:
            ensure_worker()
        except Exception:
            pass
        try:
            return verbs.dumps(verbs.call(v.name, **kwargs))
        except verbs.VerbError as e:
            return f"ERROR: {e}"

    tool.__name__ = v.name
    tool.__doc__ = v.doc
    tool.__signature__ = inspect.signature(v.fn)
    tool.__annotations__ = {k: a for k, a in v.fn.__annotations__.items() if k != "return"}
    return tool


for _v in verbs.VERBS.values():
    server.tool()(_expose(_v))


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
