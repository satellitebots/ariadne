"""Index: BM25 keyword index + dense vector storage in SQLite."""

import math
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
from rank_bm25 import BM25Okapi


class Index:
    """Hybrid index backed by SQLite, rank_bm25, and numpy."""

    def __init__(self, db_path: str | Path = "rag/index.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        # In-memory BM25 index
        self.bm25: Optional[BM25Okapi] = None
        self._tokenized: list[list[str]] = []

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                source_path TEXT NOT NULL,
                principals TEXT NOT NULL  -- JSON list of principals
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL REFERENCES documents(doc_id),
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                url TEXT NOT NULL,
                principals TEXT NOT NULL,  -- JSON list of principals
                embedding BLOB             -- serialized numpy float32
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # BM25 helpers
    # ------------------------------------------------------------------
    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Simple whitespace + punctuation tokenizer."""
        import re
        return re.findall(r'\b[a-zA-Z0-9_]+\b', text.lower())

    def _rebuild_bm25(self):
        """Rebuild the in-memory BM25 from the database (after ingest).

        Opens its own connection so it can be called after close().
        """
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                "SELECT chunk_id, text FROM chunks"
            ).fetchall()
            self._tokenized = [self.tokenize(r[1]) for r in rows]
            self._chunk_ids = [r[0] for r in rows]
            if not self._tokenized:
                self.bm25 = None
                return
            self.bm25 = BM25Okapi(self._tokenized)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------
    def add_document(self, doc_id: str, url: str, source_path: str,
                     principals: list[str]):
        import json
        self.conn.execute(
            "INSERT OR REPLACE INTO documents "
            "(doc_id, url, source_path, principals) VALUES (?,?,?,?)",
            (doc_id, url, source_path, json.dumps(principals))
        )

    def add_chunk(self, chunk_id: str, doc_id: str, chunk_index: int,
                  text: str, url: str, principals: list[str],
                  embedding: np.ndarray | list[float]):
        import json
        if not isinstance(embedding, np.ndarray):
            embedding = np.array(embedding, dtype=np.float32)
        self.conn.execute(
            "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?)",
            (chunk_id, doc_id, chunk_index, text, url,
             json.dumps(principals),
             embedding.astype(np.float32).tobytes())
        )

    def commit(self):
        self.conn.commit()

    # ------------------------------------------------------------------
    # Read / search
    # ------------------------------------------------------------------
    def search_bm25(self, query: str, top_k: int = 50) -> list[tuple[str, float]]:
        """Return (chunk_id, score) for BM25 results."""
        if self.bm25 is None:
            self._rebuild_bm25()
        if not self._tokenized:
            return []
        query_tokens = self.tokenize(query)
        scores = self.bm25.get_scores(query_tokens)
        top_indices = np.argsort(scores)[::-1][:top_k]
        # For tiny corpora BM25 may produce negative IDF/scores;
        # return top-k by score regardless, clamping negatives to 0.
        return [(self._chunk_ids[i] if i < len(self._chunk_ids) else "",
                 float(max(0, scores[i]))) for i in top_indices]

    def search_vector(self, query_vec: np.ndarray,
                      top_k: int = 50) -> list[tuple[str, float]]:
        """Return (chunk_id, cosine_similarity) for vector results."""
        rows = self.conn.execute(
            "SELECT chunk_id, embedding FROM chunks"
        ).fetchall()
        if not rows:
            return []
        chunk_ids = [r[0] for r in rows]
        embeddings = np.array([
            np.frombuffer(r[1], dtype=np.float32) for r in rows
        ])
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        normalized = embeddings / norms
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []
        sim_scores = normalized @ query_vec / query_norm
        top_indices = np.argsort(sim_scores)[::-1][:top_k]
        return [(chunk_ids[i], float(sim_scores[i]))
                for i in top_indices if sim_scores[i] > 0]

    def get_chunk(self, chunk_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT c.chunk_id, c.text, c.url, c.principals, "
            "d.source_path FROM chunks c "
            "JOIN documents d ON c.doc_id = d.doc_id "
            "WHERE c.chunk_id = ?", (chunk_id,)
        ).fetchone()
        if not row:
            return None
        import json
        return {
            "chunk_id": row[0],
            "text": row[1],
            "url": row[2],
            "principals": json.loads(row[3]),
            "source_path": row[4],
        }

    def search_with_acl(self, query: str, query_vec: np.ndarray,
                        user_principals: set[str] | list[str],
                        top_k: int = 10) -> list[dict]:
        """Hybrid search with ACL filtering. Merges BM25 + vector results."""
        from rag.retrieval import hybrid_merge

        # Get BM25 results
        bm25_results = self.search_bm25(query, top_k=top_k * 4)

        # Get vector results
        vector_results = self.search_vector(query_vec, top_k=top_k * 4)

        # Merge using reciprocal rank fusion
        merged = hybrid_merge(bm25_results, vector_results, top_k=top_k * 4)

        # Apply ACL filter
        user_set = set(user_principals) if not isinstance(user_principals, set) else user_principals
        filtered = []
        seen = set()
        for chunk_id, score in merged:
            if chunk_id in seen:
                continue
            chunk = self.get_chunk(chunk_id)
            if chunk and set(chunk["principals"]) & user_set:
                filtered.append(chunk)
                seen.add(chunk_id)
            if len(filtered) >= top_k:
                break
        return filtered

    def close(self):
        self.conn.close()
