"""B7: the draw.io path in the `diagram` server - export, read back, and a local SVG render (no browser)."""
import json
from xml.etree import ElementTree as ET

from ariadne import diagram_mcp as dg

SPEC = {
    "title": "Checkout",
    "nodes": [
        {"id": "web", "label": "Web", "x": 40, "y": 40, "shape": "rounded"},
        {"id": "api", "label": "API", "x": 280, "y": 40, "shape": "box"},
        {"id": "db", "label": "DB", "x": 280, "y": 200, "shape": "ellipse"},
        {"id": "dec", "label": "Paid?", "x": 40, "y": 200, "shape": "diamond"},
    ],
    "edges": [{"from": "web", "to": "api", "label": "POST /pay"},
              {"from": "api", "to": "db"}, {"from": "api", "to": "dec", "label": "check"}],
}


def test_export_writes_a_drawio_diagrams_net_can_open(tmp_path):
    out = tmp_path / "checkout.drawio"
    msg = dg.drawio_export(str(out), SPEC["nodes"], SPEC["edges"], title="Checkout")
    assert "wrote" in msg and "4 nodes, 3 edges" in msg and out.exists()
    root = ET.parse(out).getroot()
    assert root.tag == "mxfile"
    model = root.find("diagram/mxGraphModel")
    assert model is not None and model.find("root") is not None
    values = [c.get("value") for c in model.findall(".//mxCell") if c.get("vertex") == "1"]
    assert values == ["Web", "API", "DB", "Paid?"]
    assert any("rhombus" in (c.get("style") or "") for c in model.findall(".//mxCell"))


def test_read_returns_the_same_diagram(tmp_path):
    out = tmp_path / "c.drawio"
    dg.drawio_export(str(out), SPEC["nodes"], SPEC["edges"], title="Checkout")
    got = json.loads(dg.drawio_read(str(out)))
    assert got["title"] == "Checkout"
    assert [(n["id"], n["label"], n["shape"]) for n in got["nodes"]] == [
        ("web", "Web", "rounded"), ("api", "API", "box"), ("db", "DB", "ellipse"), ("dec", "Paid?", "diamond")]
    assert got["edges"][0] == {"from": "web", "to": "api", "label": "POST /pay"}
    assert not any(e.get("dangling") for e in got["edges"])


def test_missing_coordinates_are_laid_out_on_a_grid():
    nodes = dg._layout([{"id": "a", "label": "A"}, {"id": "b", "label": "B"},
                        {"id": "c", "label": "C"}, {"id": "d", "label": "D"}])
    assert len({(n["x"], n["y"]) for n in nodes}) == 4
    assert nodes[0]["x"] < nodes[1]["x"] and nodes[0]["y"] == nodes[1]["y"]
    assert nodes[2]["y"] > nodes[0]["y"]


def test_svg_is_rendered_locally_with_shapes_arrows_and_labels(tmp_path):
    src = tmp_path / "c.drawio"
    dg.drawio_export(str(src), SPEC["nodes"], SPEC["edges"], title="Checkout")
    out = tmp_path / "c.svg"
    msg = dg.drawio_svg(str(src), str(out))
    assert "wrote" in msg and "4 nodes, 3 edges" in msg
    svg = out.read_text(encoding="utf-8")
    assert svg.startswith("<svg") and 'marker-end="url(#arrow)"' in svg
    assert "<ellipse" in svg and "<polygon points=" in svg                    # the diamond
    for label in ("Web", "API", "DB", "Paid?", "POST /pay"):
        assert label in svg
    ET.fromstring(svg)                                                       # valid XML, not just text


def test_an_edge_to_an_unknown_node_is_refused(tmp_path):
    msg = dg.drawio_export(str(tmp_path / "x.drawio"), [{"id": "a", "label": "A"}], [{"from": "a", "to": "nope"}])
    assert "unknown node" in msg


def test_a_compressed_page_says_so(tmp_path):
    p = tmp_path / "z.drawio"
    p.write_text('<mxfile><diagram name="P" id="1">7VZNb5wwEP01HNsFzG6TY5PNpoccdmRp</diagram></mxfile>',
                 encoding="utf-8")
    assert "compressed" in dg.drawio_read(str(p))


def test_relative_paths_are_refused(tmp_path):
    assert "absolute" in dg.drawio_export("rel.drawio", SPEC["nodes"])
    assert "absolute" in dg.drawio_svg("rel.drawio", str(tmp_path / "x.svg"))
    assert "absolute" in dg.drawio_read("rel.drawio")
