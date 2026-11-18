from ariadne.web_mcp import page_text

PAGE = """<!doctype html><html><head><title>Guide - Docs</title></head><body>
<nav><a>Home</a><a>Other pages</a></nav><svg><title>icon</title></svg>
<main><h1>Writing it</h1><p>Use the <code>[project]</code>   table.</p><ul><li>one</li><li>two</li></ul>
<pre>name = "x"
version = "1"</pre>""" + "<p>filler text</p>" * 40 + """</main><footer>c 2026</footer></body></html>"""


def test_page_text_keeps_the_main_content_and_code():
    title, text = page_text(PAGE, "text/html")
    assert title == "Guide - Docs"
    assert "# Writing it" in text and "Use the [project] table." in text and "- one" in text
    assert 'name = "x"\nversion = "1"' in text
    assert "Other pages" not in text and "icon" not in text and "c 2026" not in text


def test_plain_text_passes_through():
    assert page_text('{"a": 1}', "application/json") == ("", '{"a": 1}')


def test_hermes_has_the_search_toolset_and_the_ddgs_backend():
    import toolsets
    from plugins.web.ddgs import provider  # noqa: F401 -- the keyless backend the worker homes select
    assert toolsets.TOOLSETS["search"]["tools"] == ["web_search"]
