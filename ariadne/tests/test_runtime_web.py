"""B12.5: web_search as a runtime tool: DDGS behind an injectable transport, loop dispatch, worker wiring.

No network, no model: the transport is a fake and the model is scripted, as in test_runtime.py.
"""
from ariadne import paths, runtime
from ariadne.runtime import session as session_mod
from ariadne.runtime import web as web_mod
from ariadne.tests.test_runtime import Script, say, tool_reply

RESULTS = [
    {"title": "First result", "href": "https://example.com/one", "body": "The first snippet. " + "word " * 100},
    {"title": "Second result", "href": "https://example.com/two", "body": "The second snippet."},
]


class FakeTransport:
    """Remembers what it is asked, answers from a fixed list, and may raise instead."""

    def __init__(self, results=RESULTS, error=None):
        self.results, self.error, self.seen = list(results), error, []

    def __call__(self, query, limit):
        self.seen.append((query, limit))
        if self.error is not None:
            raise self.error
        return self.results


def test_the_schema_offers_web_search_with_query_and_an_optional_limit():
    fn = web_mod.Search().offered()[0]["function"]
    assert fn["name"] == "web_search"
    assert "search" in fn["description"].lower()
    assert fn["parameters"]["required"] == ["query"]
    assert fn["parameters"]["properties"]["limit"]["type"] == "integer"


def test_two_results_come_back_numbered_with_urls_and_snippets():
    t = FakeTransport()
    out = web_mod.Search(transport=t).call("web_search", {"query": "ariadne"})
    assert "1. First result" in out and "2. Second result" in out
    assert "https://example.com/one" in out and "https://example.com/two" in out
    assert "The first snippet." in out and "The second snippet." in out
    assert t.seen == [("ariadne", 5)]                        # the limit defaults to 5
    first_snippet = out.splitlines()[2]                      # the long body is trimmed to ~300 chars
    assert 290 <= len(first_snippet) <= 310


def test_the_limit_is_clamped_to_ten_and_one():
    t = FakeTransport()
    web_mod.Search(transport=t).call("web_search", {"query": "q", "limit": 50})
    assert t.seen[-1] == ("q", 10)
    web_mod.Search(transport=t).call("web_search", {"query": "q", "limit": 0})
    assert t.seen[-1] == ("q", 1)


def test_an_empty_list_says_no_results():
    out = web_mod.Search(transport=lambda q, l: []).call("web_search", {"query": "zzz nothing"})
    assert out.startswith("(no results for 'zzz nothing'")


def test_a_transport_failure_comes_back_as_an_error_not_a_raise():
    out = web_mod.Search(transport=FakeTransport(error=RuntimeError("rate limited"))).call(
        "web_search", {"query": "q"})
    assert out.startswith("ERROR: web_search failed") and "RuntimeError" in out


def test_an_unknown_web_tool_is_an_error():
    assert web_mod.Search().call("web_fetch", {}).startswith("ERROR: no web tool 'web_fetch'")


def test_the_loop_dispatches_web_search_to_the_search(tmp_path):
    home = tmp_path / "home"
    t = FakeTransport()
    run = Script(tool_reply("web_search", {"query": "local agent harness"}), say("found it in the search"))
    answer = runtime.run("research it", home=home, workspace=str(tmp_path), phase="plan", model="m",
                         session="w1", transport=run, web=web_mod.Search(transport=t))
    assert (answer.text, answer.stopped) == ("found it in the search", "")
    tool_msg = [m for m in session_mod.load(home, "w1") if m.get("role") == "tool"][0]
    assert tool_msg["name"] == "web_search" and "https://example.com/one" in tool_msg["content"]
    names = [s["function"]["name"] for s in run.calls[0]["tools"]]
    assert "web_search" in names                              # offered on the wire, in the plan phase


def test_runtime_run_builds_a_search_for_the_run(tmp_path, monkeypatch):
    from ariadne import flows as flowlib
    from ariadne import worker as workerlib
    from ariadne.runtime import model as model_mod

    made = []

    class FakeSearch:
        def __init__(self, transport=None):
            self.transport = transport
            made.append(self)

        def offered(self):
            return []

        def call(self, name, arguments):
            return f"ERROR: fake {name}"

    monkeypatch.setattr(web_mod, "Search", FakeSearch)
    monkeypatch.setattr(model_mod, "chat", lambda messages, **kw:
                        {"content": "reported", "tool_calls": [], "raw": {"role": "assistant", "content": "reported"}})
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")    # the session lands in tmp, not the state dir

    fl = flowlib.Flow(name="coding", description="d", when="w", folder=paths.FLOWS_DIR / "coding")
    r = workerlib.runtime_run(fl, "plan", "p", str(tmp_path), "t1")
    assert r.exit_code == 0 and "reported" in r.text
    assert len(made) == 1
