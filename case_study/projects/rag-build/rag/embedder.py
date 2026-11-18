"""Embedder: call the local OpenAI-compatible embedding endpoint."""

import requests


class Embedder:
    """Wrapper around the local embedding model (OpenAI-compatible API)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8090/v1",
                 model: str = "embed"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return dense embedding vectors for a batch of texts."""
        if not texts:
            return []
        resp = requests.post(
            f"{self.base_url}/embeddings",
            json={
                "model": self.model,
                "input": texts,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        # OpenAI-compatible: data["data"] is a list of {"embedding": [...]}
        return [d["embedding"] for d in data["data"]]
