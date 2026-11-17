"""MCP server: the shared memory, for Hermes workers (stdio). Run: python -m ariadne.memory_mcp"""
import json

from mcp.server.mcpserver import MCPServer

from .memory import Memory, format_hits

server = MCPServer(
    "ariadne-memory",
    instructions=("Ariadne's durable shared memory, used by every task. Recall before you plan or act "
                  "(past tasks, repos, decisions, conventions); record what a later task would need to know."))
_mem = None


def mem():
    global _mem
    if _mem is None:
        _mem = Memory()
    return _mem


@server.tool()
def memory_recall(query: str, limit: int = 5) -> str:
    """Search the shared memory. Returns the best matching notes with their links."""
    return format_hits(mem().recall(query, limit=max(1, min(int(limit), 20))))


@server.tool()
def memory_record(kind: str, name: str, text: str, related: str = "") -> str:
    """Save a durable note. kind: e.g. repo, decision, convention, fact, person, task.
    name: short unique name within the kind. text: what to remember.
    related: optional links as 'rel kind:name' separated by ';' (e.g. 'about repo:C:/repos/x')."""
    links = []
    for part in [p.strip() for p in related.split(";") if p.strip()]:
        rel, _, target = part.partition(" ")
        tkind, _, tname = target.strip().partition(":")
        if rel and tkind and tname:
            links.append((rel, tkind, tname))
    mem().record(kind, name, text, links)
    return json.dumps({"saved": f"{kind}:{name}", "links": len(links)})


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
