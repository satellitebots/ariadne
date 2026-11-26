"""Gate: a written piece covers its outline, and an HTML piece is well formed for a browser and a phone.

    python {checks}/piece_check.py OUTLINE.md PIECE [--min-words 30]

Coverage: every item of the outline's '## Steps' list has a heading in the piece that shares its key words
(the section was written), and every section has at least --min-words words. For .html: the tags balance, there is
a viewport meta tag, no script or stylesheet is loaded from elsewhere unless allowed with --allow-external, and
wide content (tables, pre) can scroll sideways instead of widening the page on a phone. Prints every problem and
exits 1, or a one-line pass. Never raises. Model-free: what it checks is fact, not taste.
"""
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, __import__("os").path.dirname(__file__))
from plan_steps import plan_items  # noqa: E402

STOP = set("a an and the of for to in on with by from as is are be or at it its this that into how what why when "
           "your you their our step section write add make about using use".split())
VOID = set("area base br col embed hr img input link meta source track wbr".split())


def words(s):
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1]


class Shape(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.problems, self.heads, self.meta_viewport, self.external = [], [], [], False, []
        self._head, self._buf, self.sections = None, [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and (a.get("name") or "").lower() == "viewport":
            self.meta_viewport = True
        if tag == "script" and re.match(r"(https?:)?//", a.get("src") or ""):
            self.external.append(a["src"])
        if tag == "link" and "stylesheet" in (a.get("rel") or "") and re.match(r"(https?:)?//", a.get("href") or ""):
            self.external.append(a["href"])
        if tag in ("h1", "h2", "h3"):
            self._head = []
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag in ("h1", "h2", "h3") and self._head is not None:
            self.heads.append(" ".join(self._head).strip())
            self.sections.append([])
            self._head = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for t, line in self.stack[i + 1:]:
                    if t not in ("p", "li", "td", "th", "tr", "option", "dt", "dd"):     # optional end tags
                        self.problems.append(f"<{t}> opened on line {line} is not closed before </{tag}>")
                del self.stack[i:]
                return
        self.problems.append(f"</{tag}> on line {self.getpos()[0]} closes nothing")

    def handle_data(self, data):
        if self._head is not None:
            self._head.append(data)
        elif self.sections:
            self.sections[-1].append(data)


def md_sections(text):
    heads, sections = [], []
    for line in text.splitlines():
        m = re.match(r"^#{1,3}\s+(.+)$", line)
        if m:
            heads.append(m.group(1))
            sections.append([])
        elif sections:
            sections[-1].append(line)
    return heads, sections


def main(argv):
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--min-words")]
    if len(args) < 2:
        print("usage: piece_check.py OUTLINE.md PIECE [--min-words 30] [--allow-external]")
        return 2
    outline, piece = args[0], args[1]
    min_words = int(argv[argv.index("--min-words") + 1]) if "--min-words" in argv else 30
    try:
        items = plan_items(open(outline, encoding="utf-8").read())
        text = open(piece, encoding="utf-8").read()
    except OSError as e:
        print(f"cannot read: {e}")
        return 1
    problems = []
    if piece.lower().endswith((".html", ".htm")):
        p = Shape()
        try:
            p.feed(text)
            p.close()
        except Exception as e:
            problems.append(f"the HTML does not parse: {e}")
        problems += p.problems[:10]
        problems += [f"<{t}> opened on line {line} is never closed" for t, line in p.stack
                     if t not in ("html", "body", "head", "p", "li")][:10]
        if not p.meta_viewport:
            problems.append('no <meta name="viewport" content="width=device-width, initial-scale=1"> (phones zoom out)')
        if p.external and "--allow-external" not in argv:
            problems.append("loads from elsewhere (one self-contained file): " + ", ".join(p.external[:5]))
        if re.search(r"<(table|pre)\b", text, re.I) and not re.search(r"overflow(-x)?\s*:\s*(auto|scroll)", text, re.I):
            problems.append("has tables or <pre> but no 'overflow-x: auto' on them: they widen the page on a phone")
        heads, sections = p.heads, [" ".join(s) for s in p.sections]
    else:
        heads, secs = md_sections(text)
        sections = ["\n".join(s) for s in secs]
    hw = [set(words(h)) for h in heads]
    for n, item in enumerate(items, 1):
        key = set(words(item.split(":")[0])) or set(words(item))
        best = max(range(len(heads)), key=lambda j: len(key & hw[j]), default=None)
        if best is None or not key & hw[best]:
            problems.append(f"outline item {n} ('{item[:60]}') has no heading in {piece}")
    thin = [heads[j] for j, s in enumerate(sections) if len(words(s)) < min_words and j > 0]
    if thin:
        problems.append(f"section(s) with under {min_words} words: " + "; ".join(h[:40] for h in thin[:6]))
    if problems:
        print(f"{piece}:\n- " + "\n- ".join(problems))
        return 1
    print(f"ok: {piece} covers all {len(items)} outline items in {len(heads)} headings")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
