"""Citations: a content deliverable's source list is checked, not trusted (model-free).

The content flow's rule is that a claim taken from a reference carries its citation and the source list is part of
the report - not a footnote the model may skip (docs/COVERAGE.md). This module is the gate that makes that a fact:

    sources/SOURCES.md      one entry per source:   - [S1] https://example.com - what it supports
    any other *.md          a claim from a source:  ... as reported [S1].

`python -m ariadne.citations <workspace> [--strict]` exits 1 and names every marker with no entry, and (strict) every
entry never cited. The content flow runs it as a check only when a `sources/` folder exists, so a piece written
without references is not forced to invent a bibliography.
"""
import json
import re
import sys
from pathlib import Path

MARK = re.compile(r"\[(S\d+)\]")
ENTRY = re.compile(r"^\s*[-*]\s*\[(S\d+)\]\s*(.*)$")
SOURCES = "sources"
INDEX = "SOURCES.md"


def check(workspace, strict=True, sources=SOURCES) -> dict:
    """{ok, problems, listed, cited, uncited} for one workspace. Raises FileNotFoundError for a missing workspace."""
    root = Path(workspace)
    if not root.is_dir():
        raise FileNotFoundError(f"no such workspace: {workspace}")
    src = root / sources
    index = src / INDEX
    problems = []
    if not src.exists():
        problems.append(f"no {sources}/ folder: references were promised or the check was run by mistake")
        return {"ok": False, "problems": problems, "listed": [], "cited": [], "uncited": []}
    listed = {}
    if not index.exists():
        problems.append(f"{sources}/{INDEX} is missing: the source list is part of the report")
    else:
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            m = ENTRY.match(line)
            if m:
                listed[m.group(1)] = m.group(2).strip()

    cited = {}
    for md in sorted(root.rglob("*.md")):
        if src in md.parents or md == index:
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in MARK.finditer(text):
            cited.setdefault(m.group(1), []).append(md.relative_to(root).as_posix())

    for marker, where in sorted(cited.items()):
        if marker not in listed:
            problems.append(f"[{marker}] is cited in {', '.join(sorted(set(where)))} but has no entry in "
                            f"{sources}/{INDEX}")
    uncited = [k for k in sorted(listed) if k not in cited]
    if strict and uncited:
        problems.append("listed but never cited: " + ", ".join(f"[{k}]" for k in uncited))
    return {"ok": not problems, "problems": problems, "listed": sorted(listed), "cited": sorted(cited),
            "uncited": uncited}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    paths = [a for a in argv if not a.startswith("--")]
    strict, as_json = "--strict" in argv, "--json" in argv
    if not paths:
        print("usage: python -m ariadne.citations <workspace> [--strict] [--json]")
        return 2
    try:
        out = check(paths[0], strict=strict)
    except FileNotFoundError as e:
        print(str(e))
        return 2
    if as_json:
        print(json.dumps(out, indent=1))
    elif out["ok"]:
        print(f"citations: OK ({len(out['cited'])} cited, {len(out['listed'])} listed)")
    else:
        print("citations: FAIL")
        for p in out["problems"]:
            print("  - " + p)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
