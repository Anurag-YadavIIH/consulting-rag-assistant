"""
Query tracing: what was asked, what was retrieved (chunk ids + scores), how
long it took, and what it cost — the "why did it answer that?" record a
system clients rely on needs to be able to produce on demand.

Default is a no-op so tracing is invisible until you opt in by setting
LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY. No client text is sent anywhere new
by enabling this — Langfuse Cloud's free tier is documented in the README as
the default target; self-hosting is a drop-in swap via LANGFUSE_HOST.
"""

from __future__ import annotations

from typing import Protocol

from .config import settings


class Tracer(Protocol):
    def trace_query(
        self,
        *,
        query: str,
        user_id: str,
        retrieved: list[dict],
        latency_ms: float,
        answer_text: str | None = None,
        token_usage: dict | None = None,
    ) -> None:
        ...


class NoOpTracer:
    def trace_query(self, **kwargs) -> None:
        pass


class LangfuseTracer:
    """Sends one trace per query: the question, retrieved chunk ids + scores
    as a retrieval span, latency, and token usage if the LLM backend reports
    it (see rag.py:OllamaLLM.last_usage)."""

    def __init__(self):
        from langfuse import Langfuse

        self._client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )

    def trace_query(
        self,
        *,
        query: str,
        user_id: str,
        retrieved: list[dict],
        latency_ms: float,
        answer_text: str | None = None,
        token_usage: dict | None = None,
    ) -> None:
        trace = self._client.trace(name="rag-query", user_id=user_id, input=query)
        trace.span(
            name="retrieve",
            input=query,
            output=[
                {"chunk_id": c["chunk_id"], "score": c.get("score")} for c in retrieved
            ],
            metadata={"latency_ms": latency_ms},
        )
        if answer_text is not None:
            trace.generation(
                name="generate",
                input=query,
                output=answer_text,
                usage=token_usage,
                metadata={"latency_ms": latency_ms},
            )
        self._client.flush()


def build_tracer() -> Tracer:
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        return LangfuseTracer()
    return NoOpTracer()
