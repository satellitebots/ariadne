"""Tests for the hybrid retrieval merge function."""

from rag.retrieval import hybrid_merge


def test_hybrid_merge_basic():
    """Test merging BM25 and vector results."""
    bm25 = [("chunk1", 10.0), ("chunk2", 5.0)]
    vector = [("chunk2", 0.9), ("chunk3", 0.8)]
    merged = hybrid_merge(bm25, vector, top_k=10)
    assert len(merged) >= 3
    # chunk2 appears in both, should have higher rank
    chunk2_score = sum(s for cid, s in merged if cid == "chunk2")
    chunk1_score = sum(s for cid, s in merged if cid == "chunk1")
    chunk3_score = sum(s for cid, s in merged if cid == "chunk3")
    assert chunk2_score >= chunk1_score
    assert chunk2_score >= chunk3_score


def test_hybrid_merge_no_overlap():
    """Test merging when BM25 and vector have no overlap."""
    bm25 = [("a", 10.0), ("b", 5.0)]
    vector = [("c", 0.9), ("d", 0.8)]
    merged = hybrid_merge(bm25, vector, top_k=10)
    merged_ids = [cid for cid, _ in merged]
    assert "a" in merged_ids
    assert "b" in merged_ids
    assert "c" in merged_ids
    assert "d" in merged_ids


def test_hybrid_merge_empty():
    """Test merging with empty inputs."""
    merged = hybrid_merge([], [], top_k=10)
    assert merged == []


def test_hybrid_merge_top_k():
    """Test that top_k is respected."""
    bm25 = [(f"chunk{i}", float(i)) for i in range(20)]
    vector = [(f"chunk{i}", 0.1) for i in range(20, 40)]
    merged = hybrid_merge(bm25, vector, top_k=5)
    assert len(merged) <= 5


def test_hybrid_merge_duplicates():
    """Test that duplicate chunk_ids are not double-counted in output."""
    bm25 = [("same", 10.0)]
    vector = [("same", 0.9)]
    merged = hybrid_merge(bm25, vector, top_k=10)
    same_count = sum(1 for cid, _ in merged if cid == "same")
    assert same_count == 1
