"""Tests for the index module."""

import os
import tempfile
from rag.index import Index


def test_index_add_and_get():
    """Test adding and retrieving a document."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        idx = Index(db_path)
        idx.add_document("doc1", "https://k8s.io/test", "test.md", ["platform"])
        idx.commit()

        row = idx.conn.execute(
            "SELECT doc_id, url, source_path, principals FROM documents WHERE doc_id=?",
            ("doc1",)
        ).fetchone()
        assert row is not None
        assert row[0] == "doc1"
        assert row[1] == "https://k8s.io/test"
        idx.close()
    finally:
        os.unlink(db_path)


def test_index_search_bm25():
    """Test BM25 search returns results."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        idx = Index(db_path)
        idx.add_document("doc1", "https://k8s.io/test", "test.md", ["platform"])
        idx.add_chunk("chunk1", "doc1", 0,
                      "Kubernetes is a container orchestration system",
                      "https://k8s.io/test", ["platform"],
                      [0.1] * 768)
        idx.commit()
        idx._rebuild_bm25()

        results = idx.search_bm25("container orchestration", top_k=5)
        assert len(results) >= 1
        assert results[0][0] == "chunk1"
        idx.close()
    finally:
        os.unlink(db_path)


def test_index_search_vector():
    """Test vector search returns results."""
    import numpy as np
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        idx = Index(db_path)
        idx.add_document("doc1", "https://k8s.io/test", "test.md", ["platform"])
        vec = np.random.rand(768).astype(np.float32)
        idx.add_chunk("chunk1", "doc1", 0,
                      "Kubernetes pods run containers",
                      "https://k8s.io/test", ["platform"], vec)
        idx.commit()

        query_vec = np.random.rand(768).astype(np.float32)
        results = idx.search_vector(query_vec, top_k=5)
        assert len(results) >= 1
        idx.close()
    finally:
        os.unlink(db_path)


def test_index_search_empty():
    """Test search on empty index returns empty results."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        idx = Index(db_path)
        results = idx.search_bm25("test")
        assert results == []
        idx.close()
    finally:
        os.unlink(db_path)


def test_index_get_chunk():
    """Test retrieving a specific chunk by ID."""
    import numpy as np
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        idx = Index(db_path)
        vec = np.random.rand(768).astype(np.float32)
        idx.add_document("doc1", "https://k8s.io/test", "test.md", ["platform"])
        idx.add_chunk("chunk1", "doc1", 0,
                      "Test chunk text",
                      "https://k8s.io/test", ["platform"], vec)
        idx.commit()

        chunk = idx.get_chunk("chunk1")
        assert chunk is not None
        assert chunk["text"] == "Test chunk text"
        assert chunk["url"] == "https://k8s.io/test"
        idx.close()
    finally:
        os.unlink(db_path)
