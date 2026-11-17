"""MCP server: have a catalog text model draft something (stdio). Run: python -m ariadne.text_mcp

For generate-kind models (e.g. Fimbulvetr for prose) that write well but cannot drive an agent run themselves:
the step's agent model asks, gets the text back, and puts it where the plan says."""
from mcp.server.mcpserver import MCPServer

from . import llm, models

server = MCPServer("ariadne-text", instructions="Draft text with a local writing model chosen in the plan.")


@server.tool()
def generate_text(prompt: str, model: str = "", system: str = "", max_tokens: int = 1500) -> str:
    """Have `model` (a catalog model; default: the writing default) write a response to `prompt`. Returns the text.
    Give it everything it needs in the prompt: it sees nothing else (small context)."""
    cat = models.load()
    try:
        m = cat.get(model or cat.default_for("writing"))
    except models.ModelError as e:
        return str(e)
    if m.kind not in ("generate", "agent"):
        return f"{m.name} is a {m.kind} model; it does not write text"
    if not m.installed():
        return f"{m.name} is not installed: run  python -m ariadne models install {m.name}"
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    try:
        return llm.chat(m.name, msgs, max_tokens=max(64, min(int(max_tokens), 3500)), timeout=900, temperature=0.8)
    except Exception as e:
        return f"{m.name} failed: {e}"


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
