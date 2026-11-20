"""B6b: the `office` MCP server - docx and xlsx with the standard library (a docx/xlsx is a zip of XML)."""
import json
import zipfile

from ariadne import office_mcp as office

MD = """# Quarterly report

Intro paragraph with **bold** and `code`.

## Numbers

- north: 10 units
- south: 4 units

1. first
2. second

| region | units |
| --- | --- |
| north | 10 |
| south | 4 |

```python
print("hi")
```
"""


def test_a_markdown_document_becomes_a_real_docx_and_reads_back(tmp_path):
    out = tmp_path / "report.docx"
    msg = office.write_docx(str(out), MD, title="Quarterly")
    assert "wrote" in msg and out.exists()
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
    assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml"} <= names

    text = office.read_docx(str(out))
    assert "# Heading1" not in text                                  # we read levels, not style names
    assert "# Quarterly report" in text and "## Numbers" in text
    assert "• north: 10 units" in text
    assert "| region | units |" in text and "| north | 10 |" in text
    assert 'print("hi")' in text


def test_the_docx_is_a_zip_with_word_namespaces_and_escaped_text(tmp_path):
    out = tmp_path / "x.docx"
    office.write_docx(str(out), "# A & B <ok>\n\nplain", title="T")
    with zipfile.ZipFile(out) as z:
        doc = z.read("word/document.xml").decode()
    assert "&amp;" in doc and "&lt;ok&gt;" in doc
    assert "w:body" in doc and "Heading1" in doc


def test_reading_something_that_is_not_a_docx_says_so(tmp_path):
    bad = tmp_path / "x.docx"
    bad.write_text("not a zip")
    assert "BadZipFile" in office.read_docx(str(bad))
    assert "absolute" in office.write_docx("relative.docx", "hi")


def test_a_workbook_keeps_its_types_and_sheets(tmp_path):
    out = tmp_path / "book.xlsx"
    rows = [["region", "units", "price", "ok"], ["north", 10, 2.5, True], ["south", 4, 3.0, False]]
    msg = office.write_xlsx(str(out), [{"name": "Sales", "rows": rows}, {"name": "Empty", "rows": []}])
    assert "wrote" in msg and "2 sheet(s)" in msg
    assert json.loads(office.list_sheets(str(out))) == [{"sheet": "Sales", "rows": 3}, {"sheet": "Empty", "rows": 0}]
    got = json.loads(office.read_xlsx(str(out), "Sales"))
    assert got["rows"][0] == ["region", "units", "price", "ok"]
    assert got["rows"][1] == ["north", 10, 2.5, True]                 # ints stay ints, floats floats
    assert json.loads(office.read_xlsx(str(out)))["sheet"] == "Sales"  # first sheet by default


def test_bad_sheet_names_are_cleaned_and_unknown_sheets_named(tmp_path):
    out = tmp_path / "book.xlsx"
    office.write_xlsx(str(out), [{"name": "a/b:c*?[]", "rows": [[1]]}])
    names = [s["sheet"] for s in json.loads(office.list_sheets(str(out)))]
    assert names == ["a-b-c----"]
    assert "no sheet 'nope'" in office.read_xlsx(str(out), "nope")
    assert "this workbook has" in office.read_xlsx(str(out), "nope")


def test_reading_something_that_is_not_a_workbook_says_so(tmp_path):
    bad = tmp_path / "b.xlsx"
    bad.write_text("nope")
    assert "BadZipFile" in office.list_sheets(str(bad))
    assert "absolute" in office.write_xlsx("rel.xlsx", [])
