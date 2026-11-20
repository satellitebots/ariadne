"""MCP server: office - docx and xlsx, read and written with the standard library (stdio).

Run: python -m ariadne.office_mcp

A .docx or .xlsx is a zip of XML, so this needs no dependency and no Office install. The document side writes from
Markdown (the format every flow already produces): headings, bullets, numbered lists, fenced code and pipe tables
become real Word paragraphs and tables with named styles, so the result opens with a navigation pane. The sheet side
takes explicit rows, which is what a model can produce reliably.

Absolute paths only; relative paths would resolve somewhere the worker is not looking.
"""
import json
import re
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from mcp.server.mcpserver import MCPServer

server = MCPServer("ariadne-office", instructions=(
    "Read and write Word (.docx) and Excel (.xlsx) files without Word or Excel installed. Write a document from "
    "Markdown (headings, bullets, tables) when the deliverable is a document; write a sheet from rows when the "
    "deliverable is data. Read either one to get its text or its cells back."))

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CORE = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"


def _abs(path: str, what: str, must_exist: bool = False) -> Path:
    p = Path(path)
    if not p.is_absolute():
        raise ValueError(f"{what} must be an absolute path (relative paths resolve outside the workspace): {path}")
    if must_exist and not p.exists():
        raise FileNotFoundError(f"no such file: {path}")
    return p


def _zip_write(path: Path, parts: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)


# ---------- docx: Markdown in ----------

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/></w:rPr>
</w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>
 <w:rPr><w:b/><w:sz w:val="56"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
 <w:pPr><w:outlineLvl w:val="0"/><w:spacing w:before="240" w:after="120"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
 <w:pPr><w:outlineLvl w:val="1"/><w:spacing w:before="200" w:after="100"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>
 <w:pPr><w:outlineLvl w:val="2"/><w:spacing w:before="160" w:after="80"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/>
 <w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr></w:style>
</w:styles>"""


def _runs(text: str) -> str:
    """Inline runs: **bold** and `code` become their own w:r; everything else is plain."""
    out, i = [], 0
    for m in re.finditer(r"(\*\*.+?\*\*|`[^`]+`)", text or ""):
        plain = text[i:m.start()]
        if plain:
            out.append(f'<w:r><w:t xml:space="preserve">{escape(plain)}</w:t></w:r>')
        token = m.group(0)
        if token.startswith("**"):
            out.append(f'<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{escape(token[2:-2])}</w:t></w:r>')
        else:
            out.append(f'<w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr>'
                       f'<w:t xml:space="preserve">{escape(token[1:-1])}</w:t></w:r>')
        i = m.end()
    if i < len(text or ""):
        out.append(f'<w:r><w:t xml:space="preserve">{escape(text[i:])}</w:t></w:r>')
    return "".join(out) or "<w:r><w:t/></w:r>"


def _para(text: str, style: str = "") -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_runs(text)}</w:p>"


def _table(rows) -> str:
    cols = max(len(r) for r in rows)
    grid = "".join('<w:gridCol w:w="2400"/>' for _ in range(cols))
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>'
           + "".join(f'<w:{b} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
                     for b in ("top", "left", "bottom", "right", "insideH", "insideV"))
           + f"</w:tblBorders></w:tblPr><w:tblGrid>{grid}</w:tblGrid>"]
    for i, row in enumerate(rows):
        cells = list(row) + [""] * (cols - len(row))
        out.append("<w:tr>")
        for cell in cells:
            body = _runs(("**" + cell + "**") if (i == 0 and cell) else cell)
            out.append(f"<w:tc><w:tcPr/><w:p>{body}</w:p></w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out) + "<w:p/>"


def markdown_blocks(md: str):
    """Markdown -> a list of ('p'|'table', payload). Fences, headings, bullets, numbers and pipe tables."""
    blocks, table, fence, in_code = [], [], False, False
    lines = (md or "").replace("\r\n", "\n").split("\n")
    flush = lambda: (blocks.append(("table", table[:])), table.clear())
    for line in lines:
        s = line.rstrip()
        if s.strip().startswith("```"):
            if table:
                flush()
            if in_code:
                in_code = False
                blocks.append(("code", fence[:]))
            else:
                in_code, fence = True, []
            continue
        if in_code:
            fence.append(s)
            continue
        if s.strip().startswith("|") and s.strip().endswith("|"):
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
                continue                                    # the |---|---| separator
            table.append(cells)
            continue
        if table:
            flush()
        if not s.strip():
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", s.strip())
        if m:
            blocks.append(("p", (m.group(2), f"Heading{len(m.group(1))}")))
        elif re.match(r"^\s*[-*]\s+", s):
            blocks.append(("p", ("• " + re.sub(r"^\s*[-*]\s+", "", s), "")))
        elif re.match(r"^\s*\d+[.)]\s+", s):
            n = re.match(r"^\s*(\d+)[.)]", s).group(1)
            blocks.append(("p", (f"{n}. " + re.sub(r"^\s*\d+[.)]\s+", "", s), "")))
        elif s.strip().startswith(">"):
            blocks.append(("p", (s.strip().lstrip("> ").strip(), "")))
        else:
            blocks.append(("p", (s.strip(), "")))
    if table:
        flush()
    return blocks


def _document(title: str, blocks) -> str:
    body = []
    if title:
        body.append(_para(title, "Title"))
    for kind, payload in blocks:
        if kind == "table":
            body.append(_table(payload))
        elif kind == "code":
            body += [_para(line or " ", "Code") for line in payload]
        else:
            text, style = payload
            body.append(_para(text, style))
    body.append('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}</w:body></w:document>')


def _docx_parts(document: str, title: str) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "[Content_Types].xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Types xmlns="{CT}">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" '
            'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            "</Types>"),
        "_rels/.rels": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
            'core-properties" Target="docProps/core.xml"/></Relationships>'),
        "docProps/core.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<cp:coreProperties xmlns:cp="{CORE}" xmlns:dc="{DC}"><dc:title>{escape(title or "")}</dc:title>'
            f'<dc:creator>Ariadne</dc:creator><cp:lastModifiedBy>Ariadne</cp:lastModifiedBy>'
            f'<dcterms:created xmlns:dcterms="http://purl.org/dc/terms/" '
            f'xsi:type="dcterms:W3CDTF" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{now}</dcterms:created>'
            "</cp:coreProperties>"),
        "word/document.xml": document,
        "word/styles.xml": STYLES,
    }


# ---------- docx: Markdown out ----------

def _text_of(node) -> str:
    out = []
    for el in node.iter():
        tag = el.tag.split("}")[-1]
        if tag == "t":
            out.append(el.text or "")
        elif tag == "tab":
            out.append("\t")
        elif tag in ("br", "cr"):
            out.append("\n")
    return "".join(out)


def docx_to_text(xml: bytes) -> str:
    root = ET.fromstring(xml)
    body = root.find(f"{{{W}}}body")
    lines = []
    for child in list(body if body is not None else []):
        tag = child.tag.split("}")[-1]
        if tag == "p":
            style = child.find(f"{{{W}}}pPr/{{{W}}}pStyle")
            val = (style.get(f"{{{W}}}val") if style is not None else "") or ""
            text = _text_of(child)
            if val.startswith("Heading"):
                lines.append("#" * int(val[-1]) + " " + text)
            elif val == "Code":
                lines.append("    " + text)
            else:
                lines.append(text)
        elif tag == "tbl":
            for tr in child.findall(f"{{{W}}}tr"):
                cells = [_text_of(tc).strip() for tc in tr.findall(f"{{{W}}}tc")]
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
    return "\n".join(lines).strip()


# ---------- xlsx ----------

def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell_xml(ref: str, value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def _sheet_xml(rows) -> str:
    body = [f'<row r="{r}">' + "".join(_cell_xml(f"{_col(c)}{r}", v) for c, v in enumerate(row)) + "</row>"
            for r, row in enumerate(rows, 1)]
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{S}"><sheetData>{"".join(body)}</sheetData></worksheet>')


def _clean_sheet_name(name: str, i: int) -> str:
    name = re.sub(r"[\[\]:*?/\\]", "-", (name or "").strip())[:31].strip() or f"Sheet{i}"
    return name


def _xlsx_parts(sheets) -> dict:
    sheets = [{"name": _clean_sheet_name(s.get("name", ""), i + 1), "rows": s.get("rows") or []}
              for i, s in enumerate(sheets)] or [{"name": "Sheet1", "rows": []}]
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(len(sheets)))
    parts = {
        "[Content_Types].xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{CT}">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + overrides + "</Types>"),
        "_rels/.rels": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        "xl/workbook.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{S}" xmlns:r="{R}">'
            "<sheets>" + "".join(f'<sheet name="{escape(s["name"])}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                                 for i, s in enumerate(sheets)) + "</sheets></workbook>"),
        "xl/_rels/workbook.xml.rels": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{REL}">'
            + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                      'relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1)
                      for i in range(len(sheets))) + "</Relationships>"),
    }
    for i, s in enumerate(sheets):
        parts[f"xl/worksheets/sheet{i + 1}.xml"] = _sheet_xml(s["rows"])
    return parts


def _read_zip(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as z:
        return z.read(name)


def xlsx_sheets(path: Path):
    """[(sheet name, [rows])] with shared and inline strings resolved."""
    wb = ET.fromstring(_read_zip(path, "xl/workbook.xml"))
    names = [(s.get("name") or f"Sheet{i + 1}", s.get(f"{{{R}}}id"))
             for i, s in enumerate(wb.findall(f"{{{S}}}sheets/{{{S}}}sheet"))]
    rels = {}
    try:
        rel_root = ET.fromstring(_read_zip(path, "xl/_rels/workbook.xml.rels"))
        rels = {r.get("Id"): r.get("Target") for r in rel_root}
    except KeyError:
        pass
    shared = []
    try:
        ss = ET.fromstring(_read_zip(path, "xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(f"{{{S}}}t")) for si in ss.findall(f"{{{S}}}si")]
    except KeyError:
        pass
    out = []
    for i, (name, rid) in enumerate(names):
        target = (rels.get(rid) or f"worksheets/sheet{i + 1}.xml").lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        ws = ET.fromstring(_read_zip(path, target))
        rows = []
        for row in ws.findall(f".//{{{S}}}row"):
            values = {}
            for c in row.findall(f"{{{S}}}c"):
                ref = c.get("r") or ""
                letters = re.match(r"([A-Z]+)", ref)
                idx = 0
                for ch in (letters.group(1) if letters else ""):
                    idx = idx * 26 + (ord(ch) - 64)
                t = c.get("t")
                v = c.find(f"{{{S}}}v")
                if t == "s" and v is not None:
                    value = shared[int(v.text or 0)]
                elif t == "inlineStr":
                    value = "".join(x.text or "" for x in c.iter(f"{{{S}}}t"))
                elif t == "b" and v is not None:
                    value = (v.text == "1")
                elif v is not None:
                    text = v.text or ""
                    value = float(text) if "." in text or "e" in text.lower() else int(text or 0)
                else:
                    value = ""
                values[max(0, idx - 1)] = value
            rows.append([values.get(j, "") for j in range(max(values) + 1)] if values else [])
        out.append((name, rows))
    return out


# ---------- tools ----------

@server.tool()
def write_docx(path: str, markdown: str, title: str = "") -> str:
    """Write a Word document from Markdown: # headings (1-3), - bullets, 1. numbers, ``` code blocks and | pipe |
    tables become real Word paragraphs and tables. `path` and `title`: absolute path, document title."""
    try:
        out = _abs(path, "path")
        blocks = markdown_blocks(markdown)
        _zip_write(out, _docx_parts(_document(title, blocks), title))
        return f"wrote {out} ({out.stat().st_size} bytes, {len(blocks)} blocks)"
    except (OSError, ValueError) as e:
        return f"{type(e).__name__}: {e}"


@server.tool()
def read_docx(path: str) -> str:
    """A .docx as Markdown text: headings keep their level, tables become pipe rows, code keeps its indent."""
    try:
        return docx_to_text(_read_zip(_abs(path, "path", must_exist=True), "word/document.xml")) or "(empty document)"
    except (OSError, KeyError, ET.ParseError, ValueError, zipfile.BadZipFile) as e:
        return f"{type(e).__name__}: {e}"


@server.tool()
def write_xlsx(path: str, sheets: list[dict]) -> str:
    """Write an Excel workbook. sheets: [{"name": "Sheet1", "rows": [["region", "units"], ["north", 10]]}].
    Strings, numbers and booleans are typed; None/empty writes an empty cell."""
    try:
        out = _abs(path, "path")
        _zip_write(out, _xlsx_parts(sheets or []))
        return f"wrote {out} ({out.stat().st_size} bytes, {len(sheets or []) or 1} sheet(s))"
    except (OSError, ValueError, TypeError, AttributeError) as e:
        return f"{type(e).__name__}: {e}"


@server.tool()
def read_xlsx(path: str, sheet: str = "", limit: int = 200) -> str:
    """The cells of one sheet (or the first) as JSON rows, capped at `limit`; list_sheets says what is there."""
    try:
        sheets = xlsx_sheets(_abs(path, "path", must_exist=True))
        pick = next((s for s in sheets if s[0] == sheet), None) if sheet else (sheets[0] if sheets else None)
        if not pick:
            return f"no sheet '{sheet}'; this workbook has: {', '.join(n for n, _ in sheets) or '(none)'}"
        return json.dumps({"sheet": pick[0], "rows": pick[1][:max(1, min(int(limit), 2000))]}, indent=1, default=str)
    except (OSError, KeyError, ET.ParseError, ValueError, zipfile.BadZipFile) as e:
        return f"{type(e).__name__}: {e}"


@server.tool()
def list_sheets(path: str) -> str:
    """The sheets in a workbook and how many rows each has."""
    try:
        return json.dumps([{"sheet": name, "rows": len(rows)}
                           for name, rows in xlsx_sheets(_abs(path, "path", must_exist=True))], indent=1)
    except (OSError, KeyError, ET.ParseError, ValueError, zipfile.BadZipFile) as e:
        return f"{type(e).__name__}: {e}"


from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "office")


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
