"""MCP server: export documents with Pandoc (stdio), for the writing and content flows.
Run: python -m ariadne.export_mcp

Pandoc is the pinned release in serving/bin.lock (python -m ariadne install). PDF needs a PDF
engine (LaTeX, Typst, wkhtmltopdf), which is not installed: export to docx and print to PDF from Word for now."""
import subprocess
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import paths

server = MCPServer("ariadne-export", instructions="Convert a document (Markdown, HTML, docx...) to another format with Pandoc.")
FORMATS = {"docx": "docx", "html": "html", "odt": "odt", "epub": "epub", "rtf": "rtf", "md": "gfm", "txt": "plain"}


def pandoc_exe():
    from .deps import find_bin
    exe = find_bin("pandoc", "pandoc")
    if not exe:
        raise FileNotFoundError("Pandoc is not installed: run  python -m ariadne install")
    return exe


from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "export")

@server.tool()
def export_document(source: str, to: str = "docx", output: str = "") -> str:
    """Convert the file at `source` to `to` (docx, html, odt, epub, rtf, md, txt). `output` defaults to the
    source path with the new extension. Returns the output path."""
    to = to.lower().strip(".")
    if to not in FORMATS:
        return f"unsupported format '{to}'; use one of {sorted(FORMATS)} (PDF: export docx, then print to PDF)"
    src = Path(source)
    if not src.exists():
        return f"no such file: {source}"
    out = Path(output) if output else src.with_suffix("." + to)
    args = [str(pandoc_exe()), str(src), "-t", FORMATS[to], "-o", str(out)]
    if to == "html":
        args.insert(-2, "--standalone")
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if p.returncode != 0:
        return f"pandoc failed (exit {p.returncode}): {p.stderr.strip()[:2000]}"
    return f"wrote {out} ({out.stat().st_size} bytes)"


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
