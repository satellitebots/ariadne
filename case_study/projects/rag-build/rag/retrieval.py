"""Retrieval: hybrid merge of BM25 and vector search results."""

import numpy as np


def hybrid_merge(
    bm25_results: list[tuple[str, float]],
    vector_results: list[tuple[str, float]],
    top_k: int = 50,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> list[tuple[str, float]]:
    """Merge BM25 and dense vector results using Reciprocal Rank Fusion (RRF).

    Parameters
    ----------
    bm25_results: list of (chunk_id, score) from BM25, sorted by score desc.
    vector_results: list of (chunk_id, score) from vector search, sorted by score desc.
    top_k: number of merged results to return.
    bm25_weight: weight for BM25 scores (unused in RRF but kept for config).
    vector_weight: weight for vector scores (unused in RRF but kept for config).

    Returns
    -------
    List of (chunk_id, fused_score) sorted by fused score descending.
    """
    rrf_k = 60  # RRF constant

    rank_scores: dict[str, float] = {}
    for i, (chunk_id, _) in enumerate(bm25_results):
        rank_scores[chunk_id] = rank_scores.get(chunk_id, 0) + rrf_k / (rrf_k + i + 1)
    for i, (chunk_id, _) in enumerate(vector_results):
        rank_scores[chunk_id] = rank_scores.get(chunk_id, 0) + rrf_k / (rrf_k + i + 1)

    # Also add raw score normalization as tiebreaker
    raw_scores: dict[str, float] = {}
    bm25_max = max((s for _, s in bm25_results), default=1.0)
    vec_max = max((s for _, s in vector_results), default=1.0)
    for chunk_id, score in bm25_results:
        raw_scores[chunk_id] = raw_scores.get(chunk_id, 0) + score / max(bm25_max, 1e-9)
    for chunk_id, score in vector_results:
        raw_scores[chunk_id] = raw_scores.get(chunk_id, 0) + score / max(vec_max, 1e-9)

    # Combined: RRF as primary, raw score as tiebreaker
    combined = [
        (cid, rrf_scores + 0.1 * raw_scores.get(cid, 0))
        for cid, rrf_scores in rank_scores.items()
    ]
    combined.sort(key=lambda x: x[1], reverse=True)
    return combined[:top_k]
