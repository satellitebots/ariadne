"""Tiny MCP client over stdio - stands in for Claude (or any MCP client) when testing Ariadne's MCP servers.

    python tools/mcp_call.py ariadne.tasks_mcp list
    python tools/mcp_call.py ariadne.tasks_mcp submit_task '{"text": "...", "workspace": "C:/repos/x"}'
    python tools/mcp_call.py e2e <workspace> "<task text>" [--approve]   # brief -> backbrief -> sign-off -> report
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent


def params(module):
    return StdioServerParameters(command=sys.executable, args=["-m", module], cwd=str(ROOT),
                                 env=dict(os.environ, PYTHONPATH=str(ROOT)))


def text_of(result):
    return "\n".join(getattr(c, "text", str(c)) for c in result.content)


async def call(module, tool, args):
    async with stdio_client(params(module)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if tool == "list":
                return "\n".join(f"{t.name}: {(t.description or '').splitlines()[0]}" for t in (await s.list_tools()).tools)
            return text_of(await s.call_tool(tool, args, read_timeout_seconds=300))


async def e2e(workspace, text, auto_approve):
    async with stdio_client(params("ariadne.tasks_mcp")) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            sub = json.loads(text_of(await s.call_tool("submit_task", {"text": text, "workspace": workspace,
                                                                       "source": "mcp:e2e"})))
            tid = sub["id"]
            print(f"BRIEF -> task {tid}", flush=True)
            while True:
                t = json.loads(text_of(await s.call_tool("wait_task", {"id": tid, "timeout_seconds": 240},
                                                         read_timeout_seconds=300)))
                print(f"  status: {t['status']}", flush=True)
                if t["status"] == "awaiting_signoff":
                    print("BACKBRIEF:\n" + t.get("plan", ""), flush=True)
                    if not auto_approve:
                        return t
                    print("SIGN-OFF: approve", flush=True)
                    await s.call_tool("approve_task", {"id": tid})
                elif t["status"] in ("done", "failed", "cancelled", "needs_attention"):
                    print("REPORT:\n" + (t.get("result") or "") + ("\nERROR: " + t["error"] if t.get("error") else ""))
                    print("EVENTS:\n  " + "\n  ".join(t.get("events", [])))
                    return t


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "e2e":
        t = asyncio.run(e2e(a[1], a[2], "--approve" in a))
        sys.exit(0 if t["status"] in ("done", "awaiting_signoff") else 1)
    print(asyncio.run(call(a[0], a[1], json.loads(a[2]) if len(a) > 2 else {})))
