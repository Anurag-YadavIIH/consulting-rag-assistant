"""
Chunking. We split each section into overlapping windows so that retrieval
returns focused, self-contained passages rather than whole documents.

Design choices you should be able to defend in an interview:
  * We chunk by approximate token count, not characters, because the embedding
    model has a token budget and we want chunks to sit comfortably under it.
  * We keep a sentence-aware boundary so we don't cut mid-sentence, which
    otherwise produces embeddings for half-thoughts and hurts retrieval.
  * Overlap (default ~15%) preserves context that straddles a boundary.

The token counter is a cheap whitespace/punctuation approximation by default so
there are no heavy dependencies; swap in tiktoken for exact counts if you embed
with an OpenAI-compatible tokenizer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ingestion.base import RawSection

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def approx_token_count(text: str) -> int:
    # ~1 token per whitespace-or-punctuation unit; good enough for windowing.
    return len(re.findall(r"\w+|[^\w\s]", text))


@dataclass
class Chunk:
    text: str
    metadata: dict
    chunk_id: str


class Chunker:
    def __init__(self, target_tokens: int = 350, overlap_tokens: int = 50):
        if overlap_tokens >= target_tokens:
            raise ValueError("overlap must be smaller than target")
        self.target = target_tokens
        self.overlap = overlap_tokens

    def _sentences(self, text: str) -> list[str]:
        sentences = _SENTENCE_SPLIT.split(text.strip())
        return [s for s in sentences if s.strip()]

    def chunk_section(self, section: RawSection, base_id: str) -> list[Chunk]:
        sentences = self._sentences(section.text)
        chunks: list[Chunk] = []
        current: list[str] = []
        current_tokens = 0
        idx = 0

        def flush():
            nonlocal current, current_tokens, idx
            if not current:
                return
            text = " ".join(current).strip()
            chunks.append(
                Chunk(
                    text=text,
                    metadata=section.metadata(),
                    chunk_id=f"{base_id}::{idx}",
                )
            )
            idx += 1

        for sentence in sentences:
            stoks = approx_token_count(sentence)
            if current_tokens + stoks > self.target and current:
                flush()
                # start next window with overlap tail
                tail: list[str] = []
                tail_tokens = 0
                for s in reversed(current):
                    t = approx_token_count(s)
                    if tail_tokens + t > self.overlap:
                        break
                    tail.insert(0, s)
                    tail_tokens += t
                current = tail
                current_tokens = tail_tokens
            current.append(sentence)
            current_tokens += stoks

        flush()
        return chunks

    def chunk_sections(self, sections: list[RawSection]) -> list[Chunk]:
        all_chunks: list[Chunk] = []
        next_index_for_path: dict[str, int] = {}
        for section in sections:
            # Per-document counter, keyed by source_path — NOT a batch-wide
            # enumerate() index. A section's fallback locator depends only on
            # how many sections from the SAME file came before it, never on
            # what other files are in the batch or their sort order. Without
            # this, the same file's chunk_id (a PgVector key and audit
            # reference) would silently change depending on what else was
            # ingested alongside it.
            per_file_index = next_index_for_path.get(section.source_path, 0)
            next_index_for_path[section.source_path] = per_file_index + 1
            locator = section.locator or str(per_file_index)
            base = f"{section.source_path}#{locator}"
            all_chunks.extend(self.chunk_section(section, base))
        return all_chunks
