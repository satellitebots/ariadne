"""MCP server: read a web page as plain text (stdio), for looking up official docs and standards.
Run: python -m ariadne.web_mcp. Search is Hermes' own web_search (keyless ddgs backend); this reads the results."""
import html
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from mcp.server.mcpserver import MCPServer

server = MCPServer("ariadne-web", instructions=(
    "web_fetch reads a page as text. Use it on official documentation (docs.python.org, peps.python.org, the "
    "library's own docs site, PyPI) found with web_search, and cite the URL you used."))

from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "web")

SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "button"}
MAIN = re.compile(r"<(main|article)\b.*?</\1>", re.S | re.I)   # docs sites put the page in <main>/<article>
BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "section", "article", "dt", "dd"}
MAX_CHARS = 60_000


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self._in_title, self.pre = [], 0, "", False, 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag == "title" and not self.skip and not self.title:
            self._in_title = True
        elif tag == "pre":
            self.pre += 1
            self.out.append("\n```\n")
        elif tag in BLOCK:
            self.out.append("\n")
        if tag in ("h1", "h2", "h3", "h4") and not self.skip:
            self.out.append("#" * int(tag[1]) + " ")
        if tag == "li" and not self.skip:
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.out.append("\n```\n")
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data if self.pre else re.sub(r"\s+", " ", data))


def page_text(raw, content_type=""):
    if "html" not in content_type and not raw.lstrip()[:200].lower().startswith(("<!doctype", "<html")):
        return "", raw
    head = _Text()
    head.feed(raw[:raw.lower().find("</head>") + 7] if "</head>" in raw.lower() else "")
    m = MAIN.search(raw)
    p = _Text()
    p.feed(m.group(0) if m and len(m.group(0)) > 500 else raw)
    p.title = p.title or head.title
    text = re.sub(r"\n[ \t]+", "\n", "".join(p.out))
    return html.unescape(p.title.strip()), re.sub(r"\n{3,}", "\n\n", text).strip()


@server.tool()
def web_fetch(url: str, start: int = 0) -> str:
    """Read a web page (or a text/JSON file) as plain text. start: character offset to read on from, for long pages."""
    if not url.startswith(("https://", "http://")):
        return "url must start with https://"
    req = urllib.request.Request(url, headers={"User-Agent": "Ariadne/1 (docs lookup)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ctype = r.headers.get("Content-Type", "")
            raw = r.read(5_000_000).decode(r.headers.get_content_charset() or "utf-8", errors="replace")
            final = r.geturl()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} for {url}"
    except Exception as e:
        return f"could not fetch {url}: {e}"
    title, text = page_text(raw, ctype)
    part = text[start:start + MAX_CHARS]
    more = f"\n\n[{len(text) - start - len(part)} more characters: call again with start={start + len(part)}]" \
        if start + len(part) < len(text) else ""
    return f"URL: {final}\nTITLE: {title}\n\n{part}{more}"


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
