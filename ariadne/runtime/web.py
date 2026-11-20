"""The web_search tool: the flow's plan prompt already assumes it, and until now the runtime had nothing for it.

The file tools cover the workspace; this covers everything else. DDGS (DuckDuckGo, no key) is a synchronous call
that may raise on a rate limit or a dead network, so Search sits between the loop and DDGS: one OpenAI schema, and
one `call(name, arguments)` that never raises - a failure comes back as `ERROR: ...` text, which is what the model
can read and recover from. `transport` is injectable, so a test scripts the results and never touches the network.
"""


def _ddgs(query, limit):
    from ddgs import DDGS
    return DDGS().text(query, max_results=limit)


def _snippet(text, cut=300):
    text = " ".join(str(text or "").split())
    return text if len(text) <= cut else text[:cut] + "..."


class Search:
    """The web_search tool the plan prompt assumes: titles, urls and snippets for a query, capped at ten."""

    def __init__(self, transport=None):
        self.transport = transport or _ddgs

    def offered(self):
        return [{
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web; returns numbered titles, urls and snippets for the query.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "what to search for"},
                    "limit": {"type": "integer", "description": "how many results (default 5, max 10)"}},
                    "required": ["query"]}},
        }]

    def call(self, name, arguments):
        if name != "web_search":
            return f"ERROR: no web tool '{name}'"
        arguments = arguments or {}
        query = str(arguments.get("query") or "").strip()
        try:
            limit = int(arguments["limit"]) if arguments.get("limit") is not None else 5
            limit = max(1, min(limit, 10))
            results = self.transport(query, limit) or []
        except Exception as e:   # a rate limit or a dead network is a result, not a crash
            return f"ERROR: web_search failed: {type(e).__name__}: {e}"
        if not results:
            return f"(no results for '{query}')"
        return "\n".join(f"{i}. {r.get('title') or '(no title)'}\n   {r.get('href') or ''}\n   {_snippet(r.get('body'))}"
                         for i, r in enumerate(results, 1))
