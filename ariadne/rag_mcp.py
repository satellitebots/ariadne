"""MCP server: rag - ingest, chunk, embed, search, and a retrieval gate that is a number (stdio).

Run: python -m ariadne.rag_mcp

An index is one sqlite file in the workspace: the chunks, their vectors and a little metadata. Embedding is the only
call that touches a model, and it goes to the active model server (`serving.endpoint()`), so a LAN GPU box or a local
Ollama serves it. Everything else - chunking, cosine, recall@k, MRR - is arithmetic here.

`rag_eval` is how a RAG build is judged: recall@k against labelled questions must clear a threshold (`min_recall`,
default 0.8). "It runs" is not a gate; a number is (docs/COVERAGE.md).
"""
import hashlib
import json
import math
import re
import sqlite3
import urllib.request
from array import array
from pathlib import Path

from mcp.server.mcpserver import MCPServer

server = MCPServer("ariadne-rag", instructions=(
    "Build and query a local vector index. Ingest the source files, embed them (one call to the local embedding "
    "model), then search. Judge a build with rag_eval: recall@k against labelled questions must clear the "
    "threshold - report the number, never 'it works'."))

TEXT = (".md", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".csv", ".html", ".css", ".sql", ".sh", ".ps1", ".c", ".h", ".cpp", ".rs", ".go", ".java", ".rb")
SCHEMA = """CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY, source TEXT, ordinal INTEGER, text TEXT, hash TEXT, vec BLOB, dim INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source);
CREATE INDEX IF NOT EXISTS chunks_hash ON chunks(hash);"""


class RagError(RuntimeError):
    pass


def _db(index: str) -> sqlite3.Connection:
    p = Path(index)
    if not p.is_absolute():
        raise RagError(f"index must be an absolute path (relative paths resolve outside the workspace): {index}")
    if not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), isolation_level=None)   # autocommit: every write lands, no half-saved index
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _meta(c, key, value=None):
    if value is None:
        r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else ""
    c.execute("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, str(value)))


def chunk_text(text: str, size: int = 900, overlap: int = 150):
    """Paragraph-first chunks of at most `size` characters, with `overlap` carried into the next piece of a long
    paragraph. Deterministic: same text, same chunks."""
    size, overlap = max(200, int(size)), max(0, min(int(overlap), max(0, int(size) // 2 - 1)))
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= size:
            cur = (cur + "\n\n" + p).strip()
            continue
        if cur:
            chunks.append(cur)
        while len(p) > size:
            cut = p.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            chunks.append(p[:cut].strip())
            p = p[max(0, cut - overlap):].strip()
        cur = p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c]


def _files(paths):
    out = []
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            raise RagError(f"path must be absolute: {raw}")
        if p.is_dir():
            out += [f for f in sorted(p.rglob("*")) if f.is_file() and f.suffix.lower() in TEXT]
        elif p.is_file():
            out.append(p)
        else:
            raise RagError(f"no such file or directory: {raw}")
    return out


def embed_model(explicit: str = "") -> str:
    """The catalog's embed model, named the way the active server names it (Ollama uses its tag)."""
    if explicit:
        return explicit
    from . import models as modellib, serving
    try:
        cat = modellib.load()
        m = next((x for x in cat.models.values() if x.kind == "embed"), None)
    except Exception as e:
        raise RagError(f"the model catalog cannot be read: {e}")
    if not m:
        raise RagError("the catalog has no embed model; add one to serving/models.yaml")
    try:
        kind = serving.active().get("kind")
    except Exception:
        kind = "llama-server"
    return (m.ollama or {}).get("tag", m.name) if kind == "ollama" else m.name


def embed(texts, model: str = "", timeout: int = 600):
    """Vectors for the texts, in order, from the active server's OpenAI-compatible /embeddings."""
    from . import serving
    if not texts:
        return []
    url = serving.endpoint().rstrip("/") + "/embeddings"
    out = []
    for i in range(0, len(texts), 32):
        batch = texts[i:i + 32]
        body = json.dumps({"model": model or embed_model(), "input": batch}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
        except Exception as e:
            raise RagError(f"the embedding model did not answer at {url}: {e}. Start it (ariadne up) or pass "
                           f"model= with the name your server uses.")
        rows = data.get("data") or []
        if len(rows) != len(batch):
            raise RagError(f"{url} returned {len(rows)} vectors for {len(batch)} inputs")
        out += [row["embedding"] for row in sorted(rows, key=lambda x: x.get("index", 0))]
    return out


def _pack(vec):
    return array("f", vec).tobytes()


def _unpack(blob):
    a = array("f")
    a.frombytes(blob)
    return a


def _cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@server.tool()
def rag_ingest(index: str, paths: list[str], size: int = 900, overlap: int = 150) -> str:
    """Chunk files into the index (a sqlite file). paths: absolute files or folders; text-like files only. Re-ingesting
    a file replaces its chunks, so this is safe to repeat."""
    try:
        c = _db(index)
        try:
            files = _files(paths)
            added = replaced = 0
            with c:
                for f in files:
                    try:
                        text = f.read_text(encoding="utf-8", errors="replace")
                    except OSError as e:
                        continue
                    pieces = chunk_text(text, size, overlap)
                    old = c.execute("SELECT count(*) FROM chunks WHERE source=?", (str(f),)).fetchone()[0]
                    c.execute("DELETE FROM chunks WHERE source=?", (str(f),))
                    replaced += 1 if old else 0
                    c.executemany(
                        "INSERT INTO chunks(source, ordinal, text, hash) VALUES (?,?,?,?)",
                        [(str(f), i, piece, hashlib.sha1(piece.encode("utf-8")).hexdigest())
                         for i, piece in enumerate(pieces)])
                    added += len(pieces)
            _meta(c, "chunk_size", size)
            _meta(c, "overlap", overlap)
            total = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
            c.close()
            return json.dumps({"files": len(files), "files_replaced": replaced, "chunks_added": added,
                               "chunks_in_index": total, "next": "call rag_embed"}, indent=1)
        except Exception:
            c.close()
            raise
    except Exception as e:
        return f"{type(e).__name__}: {e}"


@server.tool()
def rag_embed(index: str, model: str = "", batch: int = 32) -> str:
    """Embed every chunk that has no vector yet (idempotent). model: the name the active server uses for its embed
    model; default: the catalog's embed model."""
    try:
        c = _db(index)
        try:
            rows = c.execute("SELECT id, text FROM chunks WHERE vec IS NULL OR dim = 0").fetchall()
            if not rows:
                n = c.execute("SELECT count(*) FROM chunks WHERE vec IS NOT NULL").fetchone()[0]
                c.close()
                return json.dumps({"embedded": 0, "already_embedded": n, "note": "nothing new to embed"})
            vectors = []
            step = max(1, int(batch))
            for i in range(0, len(rows), step):
                vectors += embed([r["text"] for r in rows[i:i + step]], model=model)
            with c:
                c.executemany("UPDATE chunks SET vec=?, dim=? WHERE id=?",
                              [(_pack(v), len(v), r["id"]) for r, v in zip(rows, vectors)])
            _meta(c, "model", model or embed_model())
            _meta(c, "dim", len(vectors[0]) if vectors else 0)
            c.close()
            return json.dumps({"embedded": len(rows), "dim": len(vectors[0]) if vectors else 0,
                               "model": model or embed_model()}, indent=1)
        except Exception:
            c.close()
            raise
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _search(c, query, k=5, model=""):
    q = embed([query], model=model)[0]
    scored = []
    for r in c.execute("SELECT id, source, ordinal, text, vec FROM chunks WHERE vec IS NOT NULL"):
        scored.append((_cos(q, _unpack(r["vec"])), r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"score": round(s, 4), "source": r["source"], "ordinal": r["ordinal"], "text": r["text"][:1200]}
            for s, r in scored[:max(1, int(k))]]


@server.tool()
def rag_search(index: str, query: str, k: int = 5, model: str = "") -> str:
    """The `k` chunks nearest the query, each with its score and source. The index must have been embedded."""
    try:
        c = _db(index)
        try:
            n = c.execute("SELECT count(*) FROM chunks WHERE vec IS NOT NULL").fetchone()[0]
            if not n:
                return "this index has no vectors yet: call rag_embed first"
            hits = _search(c, query, k, model)
            c.close()
            return json.dumps({"query": query, "hits": hits}, indent=1)
        except Exception:
            c.close()
            raise
    except Exception as e:
        return f"{type(e).__name__}: {e}"


@server.tool()
def rag_eval(index: str, questions: list[dict], k: int = 5, min_recall: float = 0.8, model: str = "") -> str:
    """The retrieval gate: questions: [{"question": "...", "expect": "a phrase that must appear in a retrieved
    chunk"}]. Returns recall@k, MRR and pass/fail against min_recall. This is the numeric gate a RAG build must
    clear - report it, do not describe it."""
    try:
        c = _db(index)
        try:
            if not questions:
                return "give at least one {question, expect} to evaluate"
            hits, misses = 0, []
            rr = 0.0
            for q in questions:
                got = _search(c, str(q.get("question") or ""), k, model)
                expect = str(q.get("expect") or "").lower()
                rank = next((i + 1 for i, h in enumerate(got) if expect and expect in h["text"].lower()), 0)
                if rank:
                    hits += 1
                    rr += 1.0 / rank
                else:
                    misses.append({"question": q.get("question"), "expect": expect,
                                   "top": [h["source"] + f"#{h['ordinal']}" for h in got[:k]]})
            n = len(questions)
            recall = hits / n
            c.close()
            return json.dumps({"questions": n, "k": k, f"recall@{k}": round(recall, 4),
                               "mrr": round(rr / n, 4), "min_recall": float(min_recall),
                               "pass": recall >= float(min_recall), "misses": misses}, indent=1)
        except Exception:
            c.close()
            raise
    except Exception as e:
        return f"{type(e).__name__}: {e}"


@server.tool()
def rag_stats(index: str) -> str:
    """What is in the index: chunks, sources, how many are embedded, the vector dimension and the embedding model."""
    try:
        c = _db(index)
        try:
            row = c.execute("SELECT count(*), count(DISTINCT source), count(vec) FROM chunks").fetchone()
            out = {"chunks": row[0], "sources": row[1], "embedded": row[2],
                   "dim": int(_meta(c, "dim") or 0), "model": _meta(c, "model"),
                   "chunk_size": int(_meta(c, "chunk_size") or 0)}
            c.close()
            return json.dumps(out, indent=1)
        except Exception:
            c.close()
            raise
    except Exception as e:
        return f"{type(e).__name__}: {e}"


from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "rag")


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
