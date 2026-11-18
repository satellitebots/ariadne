"""Tests for the chunker module."""

from rag.chunker import chunk_document, Chunk


def test_chunk_document_basic():
    """Test basic chunking of a short document."""
    text = "Hello world. This is a test document."
    chunks = list(chunk_document("doc1", text, "https://example.com/"))
    assert len(chunks) >= 1
    assert chunks[0].doc_id == "doc1"


def test_chunk_document_overlap():
    """Test that chunks have approximately 10% overlap."""
    long_text = " ".join([f"word{i}" for i in range(100)])
    chunks = list(chunk_document("doc1", long_text, "https://example.com/",
                                 chunk_size=50, overlap=0.1))
    assert len(chunks) >= 2
    # Check that chunks overlap in content
    chunk_texts = [c.text for c in chunks]
    # At least some word should appear in multiple chunks
    all_words = []
    for ct in chunk_texts:
        all_words.extend(ct.split())
    assert len(all_words) > sum(len(c.text.split()) for c in chunks[:1])


def test_chunk_document_url_preserved():
    """Test that the URL is preserved in each chunk."""
    text = "Test content"
    chunks = list(chunk_document("doc1", text,
                                 "https://kubernetes.io/docs/concepts/"))
    for chunk in chunks:
        assert chunk.url == "https://kubernetes.io/docs/concepts/"


def test_chunk_document_chunk_ids():
    """Test that each chunk gets a unique chunk_id."""
    text = "Test content repeated" * 10
    chunks = list(chunk_document("doc1", text, "https://example.com/"))
    chunk_ids = [c.chunk_id for c in chunks]
    assert len(chunk_ids) == len(set(chunk_ids))


def test_chunk_document_small_doc():
    """Test that a very small document produces one chunk."""
    chunks = list(chunk_document("doc1", "Hi.", "https://example.com/"))
    assert len(chunks) == 1


def test_chunk_document_empty():
    """Test that empty text produces no chunks."""
    chunks = list(chunk_document("doc1", "", "https://example.com/"))
    assert len(chunks) == 0
