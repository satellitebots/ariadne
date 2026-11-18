"""Chunker: split documents into fixed-size text chunks with overlap."""

import hashlib
from dataclasses import dataclass
from typing import Iterator


@dataclass
class Chunk:
    """A single chunk of text from a document."""
    chunk_id: str = ""
    doc_id: str = ""
    chunk_index: int = 0
    text: str = ""
    url: str = ""  # kubernetes.io URL for citation

    def __post_init__(self):
        if not self.chunk_id:
            self.chunk_id = hashlib.md5(
                f"{self.doc_id}:{self.chunk_index}".encode()
            ).hexdigest()[:12]


def chunk_document(doc_id: str, text: str, url: str,
                   chunk_size: int = 500,
                   overlap: float = 0.1) -> Iterator[Chunk]:
    """Split *text* into overlapping chunks of ~chunk_size characters.

    Parameters
    ----------
    doc_id: unique document identifier (source path).
    text: raw document text.
    url: kubernetes.io URL for citation.
    chunk_size: target characters per chunk.
    overlap: fraction of *chunk_size* to overlap between chunks.
    """
    step = max(1, int(chunk_size * (1 - overlap)))
    start = 0
    chunk_index = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        # Don't split in the middle of a word
        if end < len(text):
            space = text.rfind(' ', int(start + chunk_size * 0.5), end)
            if space > start:
                end = space
        chunk_text = text[start:end].strip()
        if chunk_text:
            yield Chunk(doc_id=doc_id, chunk_index=chunk_index,
                        text=chunk_text, url=url)
        chunk_index += 1
        start += step
