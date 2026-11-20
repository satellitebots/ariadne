"""MCP server: diagrams - Mermaid as the primary path, plus draw.io / diagrams.net files (stdio).

Run: python -m ariadne.diagram_mcp

Mermaid renders with the pinned Mermaid CLI (npx) on your installed Chrome (no browser download). draw.io is the
open-source Visio-class path: `drawio_export` writes a real .drawio that diagrams.net opens for editing, `drawio_read`
imports one (nodes, edges, text), and `drawio_svg` renders it locally without a browser or Node, so a quick look never
costs a Chrome launch."""
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from mcp.server.mcpserver import MCPServer

from . import paths

MERMAID_CLI = "@mermaid-js/mermaid-cli@11.12.0"
THEMES = ("default", "neutral", "dark", "forest")
server = MCPServer("ariadne-diagram", instructions=(
    "Diagrams for planning and design. Mermaid is the default: write the source, call check_diagram until it says "
    "ok, then render_diagram to a file, keeping the .mmd next to the picture. When the person needs to edit the "
    "diagram themselves (a Visio-class handoff), drawio_export a .drawio they can open in diagrams.net, and "
    "drawio_svg for a local preview without a browser."))


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



# ---------- draw.io / diagrams.net: the open-source Visio-class path ----------

SHAPE_STYLE = {"box": "", "rounded": "rounded=1;", "ellipse": "ellipse;", "diamond": "rhombus;"}


def _layout(nodes):
    """Nodes without x/y are placed on a square-ish grid, in order: same input, same picture."""
    out, n = [], len(nodes)
    cols = max(1, math.ceil(math.sqrt(n or 1)))
    for i, raw in enumerate(nodes):
        node = dict(raw)
        node["id"] = str(node.get("id") or f"n{i + 1}")
        node["w"] = int(node.get("w") or 160)
        node["h"] = int(node.get("h") or 60)
        if node.get("x") is None or node.get("y") is None:
            node["x"] = 40 + (i % cols) * (node["w"] + 60)
            node["y"] = 40 + (i // cols) * (node["h"] + 60)
        out.append(node)
    return out


def drawio_xml(nodes, edges, title="") -> str:
    """An uncompressed .drawio (mxGraphModel). Uncompressed on purpose: a person can read and diff it."""
    nodes = _layout(nodes or [])
    by_id = {n["id"]: n for n in nodes}
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for n in nodes:
        shape = SHAPE_STYLE.get(str(n.get("shape") or "box"), "")
        style = f"{shape}whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#555555;"
        cells.append(f'<mxCell id="{escape(n["id"])}" value="{escape(str(n.get("label") or ""))}" style="{style}" '
                     f'vertex="1" parent="1"><mxGeometry x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" '
                     f'height="{n["h"]}" as="geometry"/></mxCell>')
    for i, e in enumerate(edges or [], 1):
        src, dst = str(e.get("from") or ""), str(e.get("to") or "")
        if src not in by_id or dst not in by_id:
            raise ValueError(f"edge {i} points at an unknown node ({src!r} -> {dst!r})")
        cells.append(f'<mxCell id="e{i}" value="{escape(str(e.get("label") or ""))}" '
                     f'style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;strokeColor=#555555;" '
                     f'edge="1" parent="1" source="{escape(src)}" target="{escape(dst)}">'
                     f'<mxGeometry relative="1" as="geometry"/></mxCell>')
    page = escape(title or "Page-1", {'"': "&quot;"})
    return ('<mxfile host="ariadne" type="device">'
            f'<diagram name="{page}" id="page-1"><mxGraphModel dx="800" dy="600" grid="1" gridSize="10" page="1" '
            'pageWidth="1100" pageHeight="850"><root>' + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>")


def drawio_model(path: Path):
    """{title, nodes, edges} from a .drawio (first page). Accepts an uncompressed mxGraphModel only - a compressed
    page (deflate+base64) says so instead of returning nothing."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(raw)
    diagram = root.find("diagram")
    if diagram is None:
        raise ValueError("this file has no <diagram>; is it a .drawio?")
    model = diagram.find("mxGraphModel")
    if model is None:
        raise ValueError("this page is compressed (draw.io wrote deflate+base64); re-save it with "
                         "'File > Export as > XML' or turn off compression, then read it again")
    cells = model.findall(".//mxCell")
    nodes, edges, by_id = [], [], {}
    for c in cells:
        if c.get("vertex") == "1":
            g = c.find("mxGeometry")
            style = c.get("style") or ""
            shape = ("diamond" if "rhombus" in style else "ellipse" if "ellipse" in style
                     else "rounded" if "rounded=1" in style else "box")
            node = {"id": c.get("id") or "", "label": c.get("value") or "", "shape": shape,
                    "x": int(float(g.get("x") or 0)) if g is not None else 0,
                    "y": int(float(g.get("y") or 0)) if g is not None else 0,
                    "w": int(float(g.get("width") or 160)) if g is not None else 160,
                    "h": int(float(g.get("height") or 60)) if g is not None else 60}
            nodes.append(node)
            by_id[node["id"]] = node
        elif c.get("edge") == "1":
            edges.append({"from": c.get("source") or "", "to": c.get("target") or "", "label": c.get("value") or ""})
    for e in edges:                                   # a dangling edge is a broken diagram: say which
        if e["from"] not in by_id or e["to"] not in by_id:
            e["dangling"] = True
    return {"title": diagram.get("name") or "", "nodes": nodes, "edges": edges}


def _anchor(a, b):
    """Where a line from a to b leaves a's rectangle (mid of the side it faces)."""
    ax, ay = a["x"] + a["w"] / 2, a["y"] + a["h"] / 2
    bx, by = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    dx, dy = bx - ax, by - ay
    if abs(dx) * a["h"] >= abs(dy) * a["w"]:
        return (a["x"] + a["w"] if dx > 0 else a["x"], ay)
    return (ax, a["y"] + a["h"] if dy > 0 else a["y"])


def svg_from_model(model) -> str:
    """Straight rectangles/ellipses/diamonds, arrows and labels - enough to read a diagram without a browser."""
    nodes = model["nodes"]
    if not nodes:
        raise ValueError("the diagram has no nodes to render")
    pad = 40
    width = max(n["x"] + n["w"] for n in nodes) + pad
    height = max(n["y"] + n["h"] for n in nodes) + pad
    by_id = {n["id"]: n for n in nodes}
    out = ['<defs><marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">'
           '<polygon points="0 0, 10 3.5, 0 7" fill="#555"/></marker></defs>']
    for e in model["edges"]:
        a, b = by_id.get(e["from"]), by_id.get(e["to"])
        if not a or not b:
            continue
        x1, y1 = _anchor(a, b)
        x2, y2 = _anchor(b, a)
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#555" '
                   f'stroke-width="1.5" marker-end="url(#arrow)"/>')
        if e.get("label"):
            out.append(f'<text x="{(x1 + x2) / 2:.0f}" y="{(y1 + y2) / 2 - 4:.0f}" text-anchor="middle" '
                       f'font-family="Segoe UI, sans-serif" font-size="11" fill="#555">{escape(e["label"])}</text>')
    for n in nodes:
        x, y, w, h = n["x"], n["y"], n["w"], n["h"]
        if n["shape"] == "ellipse":
            out.append(f'<ellipse cx="{x + w / 2}" cy="{y + h / 2}" rx="{w / 2}" ry="{h / 2}" fill="#fff" '
                       f'stroke="#555" stroke-width="1.5"/>')
        elif n["shape"] == "diamond":
            out.append(f'<polygon points="{x + w / 2},{y} {x + w},{y + h / 2} {x + w / 2},{y + h} {x},{y + h / 2}" '
                       f'fill="#fff" stroke="#555" stroke-width="1.5"/>')
        else:
            rx = ' rx="10"' if n["shape"] == "rounded" else ""
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"{rx} fill="#fff" stroke="#555" '
                       f'stroke-width="1.5"/>')
        out.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 4}" text-anchor="middle" font-family="Segoe UI, sans-serif" '
                   f'font-size="13" fill="#111">{escape(str(n.get("label") or ""))}</text>')
    title = f'<title>{escape(model.get("title") or "diagram")}</title>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>{title}' + "".join(out) + "</svg>")


def _out_path(output: str, suffix: str) -> Path:
    out = Path(output)
    if not out.is_absolute():
        raise ValueError(f"output must be an absolute path inside your workspace (got '{output}')")
    if out.suffix.lower() != suffix:
        raise ValueError(f"output must end in {suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


@server.tool()
def drawio_export(output: str, nodes: list[dict], edges: list[dict] | None = None, title: str = "") -> str:
    """Write a .drawio file diagrams.net opens for editing. nodes: [{"id", "label", "x"?, "y"?, "w"?, "h"?,
    "shape"?}] with shape box|rounded|ellipse|diamond (missing x/y are laid out on a grid); edges: [{"from", "to",
    "label"?}]. Returns the path and what it contains."""
    try:
        out = _out_path(output, ".drawio")
        out.write_text(drawio_xml(nodes or [], edges or [], title), encoding="utf-8")
        return (f"wrote {out} ({len(nodes or [])} nodes, {len(edges or [])} edges). Open it in diagrams.net "
                f"(draw.io) to edit; drawio_svg gives a local preview.")
    except (OSError, ValueError) as e:
        return f"{type(e).__name__}: {e}"


@server.tool()
def drawio_read(path: str) -> str:
    """A .drawio file as JSON: {title, nodes: [{id, label, x, y, w, h, shape}], edges: [{from, to, label}]}."""
    try:
        src = Path(path)
        if not src.is_absolute():
            return "path must be an absolute path inside your workspace"
        return json.dumps(drawio_model(src), indent=1)
    except (OSError, ET.ParseError, ValueError) as e:
        return f"{type(e).__name__}: {e}"


@server.tool()
def drawio_svg(path: str, output: str) -> str:
    """Render a .drawio file to SVG locally (no Chrome, no Node): boxes, ellipses, diamonds, arrows and labels."""
    try:
        src = Path(path)
        if not src.is_absolute():
            return "path must be an absolute path inside your workspace"
        out = _out_path(output, ".svg")
        model = drawio_model(src)
        out.write_text(svg_from_model(model), encoding="utf-8")
        return f"wrote {out} ({out.stat().st_size} bytes, {len(model['nodes'])} nodes, {len(model['edges'])} edges)"
    except (OSError, ET.ParseError, ValueError) as e:
        return f"{type(e).__name__}: {e}"


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
