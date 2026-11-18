"""MCP server: Mermaid diagrams - check the syntax, render to SVG/PNG/PDF (stdio). Run: python -m ariadne.diagram_mcp

Renders with the pinned Mermaid CLI (npx) on your installed Chrome (no browser download)."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import paths

MERMAID_CLI = "@mermaid-js/mermaid-cli@11.12.0"
THEMES = ("default", "neutral", "dark", "forest")
server = MCPServer("ariadne-diagram", instructions=(
    "Mermaid diagrams for planning and design. Write the diagram as Mermaid source, call check_diagram until it "
    "says ok, then render_diagram to a file. Keep the .mmd source next to the picture so it can be edited."))


def _mmdc(src_file, out_file, theme="neutral", background="white", width=1600):
    from .deps import chrome_path
    chrome = chrome_path()
    if not chrome:
        return 1, "Chrome is not installed; Mermaid renders with it (install Google Chrome)."
    cfg = Path(tempfile.gettempdir()) / "ariadne-puppeteer.json"
    cfg.write_text(json.dumps({"executablePath": str(chrome), "headless": "shell",
                               **({"args": ["--no-sandbox"]} if not paths.WINDOWS and os.geteuid() == 0 else {})}))
    cmd = [paths.npx(), "-y", "-p", MERMAID_CLI, "mmdc", "-i", str(src_file), "-o", str(out_file), "-p", str(cfg),
           "-t", theme, "-b", background, "-w", str(int(width)), "-q"]
    env = dict(os.environ, PUPPETEER_SKIP_DOWNLOAD="1")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"could not run the Mermaid CLI: {e}"
    return p.returncode, (p.stderr or p.stdout).strip()


def _first_error(text):
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("at ")]
    return "\n".join(lines[:12])[-1500:]


from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "diagram")

@server.tool()
def check_diagram(source: str) -> str:
    """Check Mermaid source. Returns 'ok' or the parse error (line and what was expected). Changes nothing."""
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "d.mmd", Path(d) / "d.svg"
        src.write_text(source, encoding="utf-8")
        code, err = _mmdc(src, out)
        return "ok" if code == 0 and out.exists() else "error:\n" + _first_error(err)


@server.tool()
def render_diagram(source: str, output: str, theme: str = "neutral", background: str = "white",
                   width: int = 1600) -> str:
    """Render Mermaid source to `output` (.svg, .png or .pdf by extension) and save the source next to it as .mmd.
    theme: default, neutral, dark or forest. Returns the paths, or the parse error."""
    out = Path(output)
    if not out.is_absolute():  # a relative path would land in this server's own folder, not the workspace
        return f"output must be an absolute path inside your workspace (got '{output}')"
    if out.suffix.lower() not in (".svg", ".png", ".pdf"):
        return "output must end in .svg, .png or .pdf"
    if theme not in THEMES:
        return f"theme must be one of {THEMES}"
    out.parent.mkdir(parents=True, exist_ok=True)
    src = out.with_suffix(".mmd")
    # Rewrite the source only when it changed: rendering the PNG and then the SVG of the same diagram must not
    # leave the PNG looking older than its source.
    if not src.exists() or src.read_text(encoding="utf-8") != source:
        src.write_text(source, encoding="utf-8")
    code, err = _mmdc(src, out, theme, background, width)
    if code != 0 or not out.exists():
        return "error:\n" + _first_error(err)
    return f"wrote {out} and its source {src}"


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
