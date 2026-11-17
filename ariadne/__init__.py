"""Ariadne: a harness on top of a pinned, unmodified Hermes Agent.

Pieces (see the Architecture doc):
- flows.py         flow definitions -> one Hermes worker home per flow
- memory.py        durable shared memory (SQLite graph + full-text search)
- orchestrator.py  task store + the single worker: brief, backbrief, sign-off, execute
- tasks_mcp.py     MCP server that Claude, other MCP clients and the Hermes gateway use to give tasks
- memory_mcp.py    MCP server that gives Hermes workers the shared memory
- git_mcp.py       small Git MCP server for the workers
"""
