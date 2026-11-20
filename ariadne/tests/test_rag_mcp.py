"""B6d: the `rag` MCP server - ingest, chunk, embed, search and a numeric retrieval gate.

The embedding model is a loopback stub with a four-word vocabulary, so the vectors, the cosine, the ranking and
recall@k are all real - only the model is fake.
"""
import http.server
import json
import threading

import pytest

from ariadne import rag_mcp

VOCAB = ("alpha", "beta", "gamma", "delta")


class EmbedStub:
    def __init__(self):
        self.calls = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_POST(self):
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                    outer.calls.append((self.path, body))
                    rows = [{"index": i, "embedding": [float(t.lower().count(w)) for w in VOCAB]}
                            for i, t in enumerate(body.get("input") or [])]
                    payload = json.dumps({"data": rows}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception:
                    pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def stub():
    s = EmbedStub()
    yield s
    s.close()


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "a.md").write_text("alpha project notes. the alpha release is close.\n\nsecond alpha paragraph", "utf-8")
    (tmp_path / "b.md").write_text("beta design document. no alpha here.", "utf-8")
    return tmp_path


@pytest.fixture
def index(tmp_path):
    return str(tmp_path / "index.db")


def test_ingest_chunks_files_and_is_repeatable(docs, index):
    out = json.loads(rag_mcp.rag_ingest(index, [str(docs)]))
    assert out["files"] == 2 and out["chunks_in_index"] == 2
    again = json.loads(rag_mcp.rag_ingest(index, [str(docs)]))
    assert again["files_replaced"] == 2 and again["chunks_in_index"] == 2      # replaced, not duplicated
    assert json.loads(rag_mcp.rag_stats(index))["sources"] == 2


def test_embed_then_search_ranks_the_right_chunk(docs, index, stub, monkeypatch):
    monkeypatch.setenv("ARIADNE_LLM_URL", stub.url)
    rag_mcp.rag_ingest(index, [str(docs)])
    assert "no vectors yet" in rag_mcp.rag_search(index, "alpha")
    out = json.loads(rag_mcp.rag_embed(index))
    assert out["embedded"] == 2 and out["dim"] == 4
    assert json.loads(rag_mcp.rag_embed(index))["embedded"] == 0               # idempotent
    hit = json.loads(rag_mcp.rag_search(index, "alpha", k=1))["hits"][0]
    assert hit["source"].endswith("a.md") and hit["score"] > 0.9
    assert stub.calls and stub.calls[0][0].endswith("/embeddings")


def test_eval_is_a_number_and_a_verdict(docs, index, stub, monkeypatch):
    monkeypatch.setenv("ARIADNE_LLM_URL", stub.url)
    rag_mcp.rag_ingest(index, [str(docs)])
    rag_mcp.rag_embed(index)
    ok = json.loads(rag_mcp.rag_eval(index, [{"question": "alpha", "expect": "alpha release"},
                                             {"question": "beta", "expect": "beta design"}]))
    assert ok["recall@5"] == 1.0 and ok["pass"] is True and ok["mrr"] == 1.0
    bad = json.loads(rag_mcp.rag_eval(index, [{"question": "alpha", "expect": "zebra"}], min_recall=0.8))
    assert bad["recall@5"] == 0.0 and bad["pass"] is False and bad["misses"][0]["expect"] == "zebra"


def test_a_threshold_between_the_two_is_honoured(docs, index, stub, monkeypatch):
    monkeypatch.setenv("ARIADNE_LLM_URL", stub.url)
    rag_mcp.rag_ingest(index, [str(docs)])
    rag_mcp.rag_embed(index)
    half = json.loads(rag_mcp.rag_eval(index, [{"question": "alpha", "expect": "alpha"},
                                               {"question": "beta", "expect": "zebra"}], min_recall=0.5))
    assert half["recall@5"] == 0.5 and half["pass"] is True
    strict = json.loads(rag_mcp.rag_eval(index, [{"question": "alpha", "expect": "alpha"},
                                                 {"question": "beta", "expect": "zebra"}], min_recall=0.8))
    assert strict["pass"] is False


def test_stats_report_what_is_there(docs, index, stub, monkeypatch):
    monkeypatch.setenv("ARIADNE_LLM_URL", stub.url)
    rag_mcp.rag_ingest(index, [str(docs)], size=400)
    rag_mcp.rag_embed(index)
    s = json.loads(rag_mcp.rag_stats(index))
    assert s["chunks"] == 2 and s["embedded"] == 2 and s["dim"] == 4 and s["chunk_size"] == 400
    assert s["model"]


def test_chunking_is_deterministic_and_overlaps_long_paragraphs():
    text = "First sentence here. " * 60
    a = rag_mcp.chunk_text(text, size=300, overlap=80)
    b = rag_mcp.chunk_text(text, size=300, overlap=80)
    assert a == b and len(a) > 1 and all(len(c) <= 300 for c in a)
    tail = a[0][-40:].strip()          # the overlap carries the end of one chunk into the start of the next
    assert any(tail[:15] in c for c in a[1:])
    assert rag_mcp.chunk_text("   ") == []


def test_bad_inputs_come_back_as_text(tmp_path):
    assert "absolute" in rag_mcp.rag_ingest("index.db", [str(tmp_path)])
    assert "no such file" in rag_mcp.rag_ingest(str(tmp_path / "i.db"), [str(tmp_path / "nope")])
    assert "no vectors yet" in rag_mcp.rag_search(str(tmp_path / "empty.db"), "x")
    assert "at least one" in rag_mcp.rag_eval(str(tmp_path / "empty.db"), [])


def test_a_dead_embedding_server_says_what_to_do(docs, index, monkeypatch):
    monkeypatch.setenv("ARIADNE_LLM_URL", "http://127.0.0.1:1/v1")
    rag_mcp.rag_ingest(index, [str(docs)])
    msg = rag_mcp.rag_embed(index)
    assert "did not answer" in msg and "ariadne up" in msg
