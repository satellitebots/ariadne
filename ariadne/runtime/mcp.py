"""MCP servers as runtime tools: spawned over stdio, namespaced `mcp__<server>__<tool>`.

A run starts the flow's servers and stops them with it, so a server cannot outlive the task that used it. The
connection lives in its own thread with one asyncio loop, because the MCP client is async and `loop.py` is not; calls
cross the boundary through a queue. One loop for the whole pool also keeps anyio's cancel scopes in the task that
opened them, which is the bug you get from calling `run_coroutine_threadsafe` per request.

Read-only phases are filtered by the flow's `plan_tools` - the list the plan prompt is already written against - so a
plan cannot commit, write a file or trigger a pipeline. That is data the repo already carries, not a guess at which
tool names mutate.

The Pool never raises at a caller: a server that will not start, a tool that times out, or a server that answers with
an error all come back as `ERROR: ...` text, which is what the model can read and recover from.
"""
import asyncio
import concurrent.futures
import json
import os
import queue
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PREFIX = "mcp__"
MAX_OUTPUT = 8000
MAX_DESCRIPTION = 1200
START_TIMEOUT = 120


def _split(full: str):
    parts = str(full or "").split("__", 2)
    if len(parts) != 3 or parts[0] != "mcp":
        raise ValueError(f"{full!r} is not an mcp tool name (mcp__<server>__<tool>)")
    return parts[1], parts[2]


def _bare(full: str) -> str:
    try:
        return _split(full)[1]
    except ValueError:
        return ""


def _schema(server, tool):
    spec = tool.input_schema or {}
    params = {"type": "object", "properties": spec.get("properties") or {}}
    if spec.get("required"):
        params["required"] = list(spec["required"])
    return {"type": "function", "function": {
        "name": f"{PREFIX}{server}__{tool.name}",
        "description": (tool.description or "")[:MAX_DESCRIPTION],
        "parameters": params}}


def _text(result) -> str:
    parts = []
    for c in getattr(result, "content", None) or []:
        text = getattr(c, "text", None)
        parts.append(text if text is not None else f"[{getattr(c, 'type', 'content')}]")
    if not parts and getattr(result, "structured_content", None):
        parts.append(json.dumps(result.structured_content, ensure_ascii=False))
    body = "\n".join(parts) or "(no output)"
    if len(body) > MAX_OUTPUT:
        body = body[:MAX_OUTPUT] + f"\n[... {len(body) - MAX_OUTPUT} more characters]"
    return ("ERROR: " if getattr(result, "is_error", False) else "") + body


def _env(cfg):
    """The child's environment: the process's own plus the flow's additions. A partial env (PYTHONPATH only)
    would strip PATH and SystemRoot, and a Python server would not start on Windows."""
    env = {str(k): str(v) for k, v in os.environ.items()}
    env.update({str(k): str(v) for k, v in (cfg.get("env") or {}).items()})
    return env


class Pool:
    """The flow's MCP servers, connected and ready to answer. Use as `Pool(cfg, plan_allowed=...)` then `close()`."""

    def __init__(self, configs, *, plan_allowed=(), timeout=START_TIMEOUT):
        self.configs = dict(configs or {})
        self.plan_allowed = set(plan_allowed or ())
        self.timeout = timeout
        self.schemas = []                 # every tool, namespaced
        self.connected = set()
        self.errors = []                  # one line per server that did not attach, for the run's log
        self.skipped = {}                 # name -> why it was not attached (e.g. an HTTP server)
        self._q = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ariadne-mcp")
        self._thread.start()
        if not self._ready.wait(timeout):
            self.errors.append(f"the MCP servers did not start within {timeout} s")

    # ---- the boundary the sync loop uses ----
    def offered(self, read_only=False):
        if not read_only:
            return list(self.schemas)
        return [s for s in self.schemas if _bare(s["function"]["name"]) in self.plan_allowed]

    def call(self, full, arguments, read_only=False, timeout=None):
        if read_only and _bare(full) not in self.plan_allowed:
            return f"ERROR: {full} is not available in the plan phase (read-only)"
        try:
            server, _tool = _split(full)
        except ValueError as e:
            return f"ERROR: {e}"
        if server not in self.connected:
            return f"ERROR: the {server} server is not connected; it did not start"
        fut = concurrent.futures.Future()
        self._q.put((full, arguments or {}, fut))
        try:
            return fut.result(timeout or self.timeout)
        except concurrent.futures.TimeoutError:
            return f"ERROR: {full} did not answer within {timeout or self.timeout} s"
        except Exception as e:
            return f"ERROR: {full} failed: {type(e).__name__}: {e}"

    def close(self, wait=5):
        self._q.put(None)
        self._thread.join(wait)

    # ---- the async side: one task owns every connection ----
    def _run(self):
        try:
            asyncio.run(self._main())
        except BaseException as e:  # startup failure: report it, never take the run down
            self.errors.append(f"{type(e).__name__}: {e}")
        finally:
            self._ready.set()

    async def _main(self):
        # One task owns every connection and every cancel scope; the stack closes them all when it leaves.
        async with AsyncExitStack() as stack:
            sessions = {}
            for name, cfg in self.configs.items():
                if cfg.get("url"):
                    self.skipped[name] = "an HTTP MCP server; the runtime attaches stdio servers only"
                    continue
                try:
                    params = StdioServerParameters(command=cfg["command"], args=list(cfg.get("args") or []),
                                                    env=_env(cfg))
                    read, write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    for tool in (await session.list_tools()).tools:
                        self.schemas.append(_schema(name, tool))
                    sessions[name] = session
                    self.connected.add(name)
                except BaseException as e:
                    self.errors.append(f"{name}: {type(e).__name__}: {e}")
            self._ready.set()
            while True:
                item = await asyncio.to_thread(self._q.get)
                if item is None:
                    return
                full, args, fut = item
                try:
                    server, tool = _split(full)
                    fut.set_result(_text(await sessions[server].call_tool(tool, args)))
                except BaseException as e:
                    fut.set_exception(e)
