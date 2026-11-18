"""Eval: run the golden set and compute hit rate."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class EvalResult:
    """Result for a single golden-set question."""
    question: str
    expected_urls: list[str]
    retrieved_urls: list[str]
    hit: bool  # True if any expected URL is in retrieved

    @property
    def precision(self) -> float:
        if not self.retrieved_urls:
            return 0.0
        return sum(1 for u in self.retrieved_urls if u in self.expected_urls) / len(self.retrieved_urls)

    @property
    def recall(self) -> float:
        if not self.expected_urls:
            return 0.0
        return sum(1 for u in self.expected_urls if u in self.retrieved_urls) / len(self.expected_urls)


@dataclass
class EvalSummary:
    """Summary over all eval results."""
    total: int = 0
    hits: int = 0
    avg_precision: float = 0.0
    avg_recall: float = 0.0
    results: list[EvalResult] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.hits / self.total


def load_golden_set(path: str | Path = "eval/golden.yaml") -> list[dict]:
    """Load the golden set from a YAML file.

    Format:
    questions:
      - question: "What is a Pod?"
        expected_urls:
          - "https://kubernetes.io/docs/concepts/workloads/pods/"
      ...
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("questions", [])


def run_eval(index, embedder, generator, question: str,
             user_principals: set[str], top_k: int = 5) -> EvalResult:
    """Run a single eval question through the full pipeline.

    Returns EvalResult with hit/precision/recall.
    """
    # Step 1: Embed the query
    query_vec = embedder.embed([question])[0]

    # Step 2: Hybrid search with ACL
    chunks = index.search_with_acl(
        query=question,
        query_vec=query_vec,
        user_principals=list(user_principals),
        top_k=top_k,
    )

    # Step 3: Get retrieved URLs
    retrieved_urls = [c["url"] for c in chunks]

    # Load golden set to get expected URLs
    golden = load_golden_set()
    expected_urls = []
    for g in golden:
        if g["question"] == question:
            expected_urls = g.get("expected_urls", [])
            break

    return EvalResult(
        question=question,
        expected_urls=expected_urls,
        retrieved_urls=retrieved_urls,
        hit=bool(set(expected_urls) & set(retrieved_urls)),
    )


def run_eval_set(index, embedder, generator,
                 user_principals: Optional[set[str]] = None,
                 top_k: int = 5) -> EvalSummary:
    """Run the full golden set and return a summary."""
    if user_principals is None:
        user_principals = {"alice", "security", "platform"}

    golden = load_golden_set()
    summary = EvalSummary(total=len(golden))

    for q in golden:
        result = run_eval(
            index=index,
            embedder=embedder,
            generator=generator,
            question=q["question"],
            user_principals=user_principals,
            top_k=top_k,
        )
        summary.results.append(result)
        if result.hit:
            summary.hits += 1
        summary.avg_precision += result.precision
        summary.avg_recall += result.recall

    if summary.total > 0:
        summary.avg_precision /= summary.total
        summary.avg_recall /= summary.total

    return summary
