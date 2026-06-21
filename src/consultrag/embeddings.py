"""
Embeddings. Default backend is sentence-transformers running locally on CPU
(model weights cached on disk, no network calls at query time) — this keeps the
confidentiality promise: client text is vectorized on your own hardware.

The `Embedder` protocol lets us inject a deterministic fake embedder in tests so
the suite runs without downloading any model.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray:
        ...


class LocalEmbedder:
    """
    Wraps a sentence-transformers model. Default is bge-small-en-v1.5: small,
    fast on CPU, strong retrieval quality for its size.

    Install: pip install sentence-transformers
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vecs, dtype=np.float32)


class OpenAIEmbedder:
    """
    OpenAI text-embedding-3-large. Sends chunk/query text to OpenAI's API —
    this is opt-in (`--embedder openai` / config), never the default, since the
    project's local-first default keeps text on-machine. Requires
    OPENAI_API_KEY (see config.py).

    Install: pip install openai
    """

    def __init__(self, model_name: str = "text-embedding-3-large"):
        from openai import OpenAI

        from .config import settings

        self._client = OpenAI(api_key=settings.openai_api_key)
        self.model_name = model_name
        self.dim = 3072

    def embed(self, texts: list[str]) -> np.ndarray:
        resp = self._client.embeddings.create(model=self.model_name, input=texts)
        vecs = np.array([d.embedding for d in resp.data], dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms


class HashEmbedder:
    """
    Dependency-free deterministic embedder for tests and offline demos.
    NOT for real retrieval quality — it just maps tokens into a fixed space so
    the pipeline, vector store, and eval harness can be exercised end to end
    without downloading a model.
    """

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for token in text.lower().split():
                h = int(hashlib.md5(token.encode()).hexdigest(), 16)
                out[i, h % self.dim] += 1.0
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
        return out
