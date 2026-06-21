"""
A small local vector store.

Implemented from scratch on NumPy on purpose:
  * It keeps everything on local disk — no external database, no data egress,
    which is the whole point of the confidentiality story.
  * Writing the cosine-similarity search yourself means you can explain exactly
    what retrieval does in an interview instead of pointing at a black box.

For larger corpora, the same interface drops onto FAISS (approximate nearest
neighbour) or Chroma. The search signature is identical so it's a one-file swap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np


@dataclass
class StoredChunk:
    chunk_id: str
    text: str
    metadata: dict


class NumpyVectorStore:
    def __init__(self, dim: int):
        self.dim = dim
        self._vectors = np.zeros((0, dim), dtype=np.float32)
        self._chunks: list[StoredChunk] = []

    def __len__(self) -> int:
        return len(self._chunks)

    def all_chunks(self) -> list[StoredChunk]:
        """Read-only snapshot of every stored chunk — used by retrievers (e.g.
        BM25) that need full-corpus access rather than a single nearest-neighbour
        query."""
        return list(self._chunks)

    def add(self, vectors: np.ndarray, chunks: list[StoredChunk]) -> None:
        if vectors.shape[0] != len(chunks):
            raise ValueError("vectors and chunks length mismatch")
        if vectors.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {vectors.shape[1]}")
        self._vectors = np.vstack([self._vectors, vectors.astype(np.float32)])
        self._chunks.extend(chunks)

    def search(self, query_vec: np.ndarray, top_k: int = 5, user=None) -> list[dict]:
        # `user` exists for interface parity with PgVectorStore.search(), which
        # uses it for a defense-in-depth SQL WHERE filter. This in-memory store
        # has no SQL layer, so it's accepted and ignored — AccessPolicy.filter()
        # (applied by RAGEngine after retrieval) is the sole access gate here.
        if len(self._chunks) == 0:
            return []
        q = query_vec.reshape(-1)
        q = q / (np.linalg.norm(q) + 1e-12)
        # vectors are stored normalized, so dot product == cosine similarity
        sims = self._vectors @ q
        k = min(top_k, len(self._chunks))
        # argpartition for top-k, then sort just those
        idx = np.argpartition(-sims, k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]
        results = []
        for i in idx:
            c = self._chunks[i]
            results.append(
                {
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "metadata": c.metadata,
                    "score": float(sims[i]),
                }
            )
        return results

    # ---- persistence -----------------------------------------------------
    def save(self, directory: str | Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "vectors.npy", self._vectors)
        with open(directory / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in self._chunks:
                f.write(json.dumps(asdict(c)) + "\n")
        with open(directory / "meta.json", "w", encoding="utf-8") as f:
            json.dump({"dim": self.dim}, f)

    @classmethod
    def load(cls, directory: str | Path) -> "NumpyVectorStore":
        directory = Path(directory)
        with open(directory / "meta.json", encoding="utf-8") as f:
            dim = json.load(f)["dim"]
        store = cls(dim=dim)
        store._vectors = np.load(directory / "vectors.npy")
        chunks: list[StoredChunk] = []
        with open(directory / "chunks.jsonl", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                chunks.append(StoredChunk(**d))
        store._chunks = chunks
        return store
