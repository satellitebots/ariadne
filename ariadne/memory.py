"""Durable shared memory for the whole harness.

One SQLite file (.ariadne/memory.db) that every task reads and writes: the orchestrator records each task
and its outcome, and Hermes workers recall and record through the memory MCP server. It is a small graph:
- nodes:  kind + name (unique together) + text, e.g. ("repo", "C:/repos/x", "Python 3.12, tests in tests/")
- edges:  src --rel--> dst between nodes, e.g. task --ran_in--> repo
- recall: full-text search (FTS5) over node names and text, best matches first, with each hit's neighbours.
"""
import json
import re
import sqlite3
import time
from contextlib import contextmanager

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL, updated REAL NOT NULL, UNIQUE(kind, name));
CREATE TABLE IF NOT EXISTS edges(
  src INTEGER NOT NULL REFERENCES nodes(id), rel TEXT NOT NULL, dst INTEGER NOT NULL REFERENCES nodes(id),
  created REAL NOT NULL, PRIMARY KEY(src, rel, dst));
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(kind, name, text, content='nodes', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
  INSERT INTO nodes_fts(rowid, kind, name, text) VALUES (new.id, new.kind, new.name, new.text); END;
CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
  INSERT INTO nodes_fts(nodes_fts, rowid, kind, name, text) VALUES ('delete', old.id, old.kind, old.name, old.text);
  INSERT INTO nodes_fts(rowid, kind, name, text) VALUES (new.id, new.kind, new.name, new.text); END;
"""


class Memory:
    def __init__(self, db_path=None):
        self.db_path = str(db_path or paths.MEMORY_DB)
        if db_path is None:
            paths.ensure()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def _upsert(self, c, kind, name, text=None):
        now = time.time()
        row = c.execute("SELECT id, text FROM nodes WHERE kind=? AND name=?", (kind, name)).fetchone()
        if row:
            if text is not None and text != row["text"]:
                c.execute("UPDATE nodes SET text=?, updated=? WHERE id=?", (text, now, row["id"]))
            return row["id"]
        cur = c.execute("INSERT INTO nodes(kind, name, text, created, updated) VALUES (?,?,?,?,?)",
                        (kind, name, text or "", now, now))
        return cur.lastrowid

    def record(self, kind, name, text="", links=None):
        """Create or update node (kind, name). links: [(rel, kind, name), ...] edges from this node."""
        kind, name = kind.strip().lower(), name.strip()
        if not kind or not name:
            raise ValueError("kind and name are required")
        with self._conn() as c:
            nid = self._upsert(c, kind, name, text)
            for rel, dkind, dname in links or []:
                did = self._upsert(c, dkind.strip().lower(), dname.strip())
                c.execute("INSERT OR IGNORE INTO edges(src, rel, dst, created) VALUES (?,?,?,?)",
                          (nid, rel.strip().lower(), did, time.time()))
        return nid

    def link(self, src_kind, src_name, rel, dst_kind, dst_name):
        return self.record(src_kind, src_name, None, [(rel, dst_kind, dst_name)])

    def _neighbours(self, c, nid):
        out = c.execute("SELECT e.rel, n.kind, n.name FROM edges e JOIN nodes n ON n.id=e.dst WHERE e.src=?",
                        (nid,)).fetchall()
        inc = c.execute("SELECT e.rel, n.kind, n.name FROM edges e JOIN nodes n ON n.id=e.src WHERE e.dst=?",
                        (nid,)).fetchall()
        return ([f"--{r['rel']}--> {r['kind']}:{r['name']}" for r in out]
                + [f"<--{r['rel']}-- {r['kind']}:{r['name']}" for r in inc])

    def recall(self, query, limit=5, kind=None):
        """Best full-text matches for query (any word may match), newest first among equals."""
        words = [w for w in re.findall(r"\w+", query or "") if len(w) > 1]
        if not words:
            return []
        fts = " OR ".join(f'"{w}"' for w in words[:24])
        sql = ("SELECT n.id, n.kind, n.name, n.text, n.updated FROM nodes_fts f JOIN nodes n ON n.id=f.rowid "
               "WHERE nodes_fts MATCH ?" + (" AND n.kind=?" if kind else "") +
               " ORDER BY bm25(nodes_fts), n.updated DESC LIMIT ?")
        params = [fts] + ([kind.lower()] if kind else []) + [int(limit)]
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
            return [{"kind": r["kind"], "name": r["name"], "text": r["text"],
                     "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["updated"])),
                     "links": self._neighbours(c, r["id"])} for r in rows]

    def get(self, kind, name):
        with self._conn() as c:
            r = c.execute("SELECT id, kind, name, text FROM nodes WHERE kind=? AND name=?",
                          (kind.lower(), name)).fetchone()
            if not r:
                return None
            return {"kind": r["kind"], "name": r["name"], "text": r["text"], "links": self._neighbours(c, r["id"])}

    def stats(self):
        with self._conn() as c:
            return {"nodes": c.execute("SELECT count(*) FROM nodes").fetchone()[0],
                    "edges": c.execute("SELECT count(*) FROM edges").fetchone()[0]}


def format_hits(hits):
    """Hits as short text for a prompt."""
    if not hits:
        return "(nothing relevant in shared memory)"
    lines = []
    for h in hits:
        lines.append(f"- [{h['kind']}] {h['name']} ({h['updated']}): {h['text'][:400]}")
        for l in h["links"][:6]:
            lines.append(f"    {l}")
    return "\n".join(lines)


if __name__ == "__main__":  # python -m ariadne.memory "query"  -> quick look from a shell
    import sys
    print(json.dumps(Memory().recall(" ".join(sys.argv[1:]) or "task"), indent=2))
