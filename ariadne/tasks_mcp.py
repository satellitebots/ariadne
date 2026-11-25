"""Kept so `python -m ariadne.tasks_mcp` in older client configs still works: it is the generated MCP front (front_mcp.py)."""
from .front_mcp import main, server  # noqa: F401

if __name__ == "__main__":
    main()
