"""
Query side: question -> embed -> retrieve -> ACCESS FILTER -> prompt -> answer.

The LLM is pluggable. Default is a local model served by Ollama (so prompts and
retrieved client text stay on your hardware). A deterministic ExtractiveLLM is
included so the system produces grounded answers with zero model downloads —
useful for demos and for the test suite.

Answers are grounded: the prompt instructs the model to answer only from the
provided context and to cite sources by their locator, and the response object
carries the supporting chunks so a user can verify every claim.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from .audit import AuditLog
from .embeddings import Embedder
from .reranking import NoOpReranker, Reranker
from .retrieval import HybridRetriever, Retriever
from .security.access import AccessPolicy, User
from .tracing import Tracer, build_tracer
from .vectorstore import NumpyVectorStore


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str:
        ...


SYSTEM_PROMPT = (
    "You are a research assistant for management consultants. Answer ONLY using "
    "the provided context. If the context is insufficient, say so plainly. "
    "Cite the source file and locator (slide/page/timestamp) for each claim. "
    "Never invent figures or sources."
)


@dataclass
class Citation:
    source_path: str
    locator: str
    score: float


@dataclass
class Answer:
    text: str
    citations: list[Citation]
    used_chunks: list[dict]


def _format_context(chunks: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        m = c["metadata"]
        tag = f"{m.get('source_path','?')} [{m.get('locator','')}]".strip()
        blocks.append(f"[{i}] Source: {tag}\n{c['text']}")
    return "\n\n".join(blocks)


class OllamaLLM:
    """Local LLM via Ollama. Install Ollama, then `ollama pull llama3.1:8b`."""

    def __init__(self, model: str = "llama3.1:8b", host: str = "http://localhost:11434"):
        self.model = model
        self.host = host
        self.last_usage: dict | None = None

    def complete(self, system: str, user: str) -> str:
        import requests  # only needed for this backend

        resp = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        body = resp.json()
        # Ollama reports token counts per response; stash them for the tracer
        # to pick up (LLM.complete's signature stays string-in/string-out).
        self.last_usage = {
            "prompt_tokens": body.get("prompt_eval_count"),
            "completion_tokens": body.get("eval_count"),
        }
        return body["message"]["content"]


class ExtractiveLLM:
    """
    No-dependency fallback. Doesn't 'generate' — it returns the most relevant
    retrieved passages with their citations. Keeps demos fully offline and makes
    the grounding obvious (the answer is literally the evidence).
    """

    def complete(self, system: str, user: str) -> str:
        marker = "CONTEXT:\n"
        context = user.split(marker, 1)[-1] if marker in user else user
        first = context.strip().split("\n\n")[0]
        return (
            "Based on the retrieved material:\n\n" + first +
            "\n\n(Offline extractive mode — connect an LLM backend for synthesis.)"
        )


class RAGEngine:
    def __init__(
        self,
        embedder: Embedder,
        store: NumpyVectorStore,
        llm: LLM | None = None,
        access_policy: AccessPolicy | None = None,
        audit: AuditLog | None = None,
        top_k: int = 5,
        retriever: Retriever | None = None,
        reranker: Reranker | None = None,
        fused_k: int = 20,
        tracer: Tracer | None = None,
    ):
        self.embedder = embedder
        self.store = store
        self.llm = llm or ExtractiveLLM()
        self.access = access_policy or AccessPolicy()
        self.audit = audit
        self.top_k = top_k
        self.retriever = retriever or HybridRetriever(store)
        self.reranker = reranker or NoOpReranker()
        self.fused_k = fused_k
        self.tracer = tracer or build_tracer()

    def retrieve(self, query: str, user: User, *, fused_k: int | None = None) -> list[dict]:
        # Fuse dense + BM25 candidates (dense leg gets a defense-in-depth SQL
        # filter when the store supports it — see PgVectorStore), drop
        # anything the user can't see, THEN rerank what's left — a blocked
        # chunk never reaches the reranker.
        qvec = self.embedder.embed([query])[0]
        raw = self.retriever.retrieve(qvec, query, fused_k=fused_k or self.fused_k, user=user)
        allowed = self.access.filter(user, raw)
        n_blocked = len(raw) - len(allowed)
        reranked = self.reranker.rerank(query, allowed, top_k=self.top_k)
        if self.audit:
            self.audit.log_query(
                user_id=user.user_id,
                query=query,
                retrieved_ids=[c["chunk_id"] for c in reranked],
                n_blocked=n_blocked,
            )
        return reranked

    def answer(self, query: str, user: User) -> Answer:
        start = time.perf_counter()
        chunks = self.retrieve(query, user)
        if not chunks:
            latency_ms = (time.perf_counter() - start) * 1000
            self.tracer.trace_query(
                query=query, user_id=user.user_id, retrieved=[], latency_ms=latency_ms,
                answer_text=None, token_usage=None,
            )
            return Answer(
                text="No accessible material matched this question.",
                citations=[],
                used_chunks=[],
            )
        context = _format_context(chunks)
        user_prompt = f"QUESTION: {query}\n\nCONTEXT:\n{context}"
        text = self.llm.complete(SYSTEM_PROMPT, user_prompt)
        latency_ms = (time.perf_counter() - start) * 1000
        citations = [
            Citation(
                source_path=c["metadata"].get("source_path", "?"),
                locator=c["metadata"].get("locator", ""),
                score=c["score"],
            )
            for c in chunks
        ]
        self.tracer.trace_query(
            query=query,
            user_id=user.user_id,
            retrieved=chunks,
            latency_ms=latency_ms,
            answer_text=text,
            token_usage=getattr(self.llm, "last_usage", None),
        )
        return Answer(text=text, citations=citations, used_chunks=chunks)
