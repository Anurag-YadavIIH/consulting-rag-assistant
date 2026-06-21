"""
Typed configuration, loaded from environment variables / a local `.env` file.

Nothing in the offline pipeline (redaction, chunking, the NumPy vector store,
the extractive LLM) reads from this module — it exists for the optional hosted
backends (LLM APIs, Postgres/pgvector, OAuth) so they have one typed place to
pull config from instead of scattered `os.environ` calls. Every field has a
default, so importing this module with zero environment variables set (the
offline demo's situation) is always safe.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Hosted LLM / search API keys — unset by default (offline mode needs none).
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    tavily_api_key: str | None = None

    # Local Ollama backend (see rag.py:OllamaLLM).
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # Postgres/pgvector, for swapping in the docker-compose Postgres service
    # as a vector store backend instead of the local NumPy store.
    database_url: str = "postgresql://consultrag:consultrag@localhost:5432/consultrag"

    # OAuth/OIDC placeholders for wiring RBAC (security/access.py) to a real
    # identity provider instead of in-process User objects.
    oauth_issuer: str | None = None
    oauth_audience: str | None = None
    oauth_jwks_url: str | None = None

    # Langfuse query tracing (tracing.py). Unset = tracing is a no-op.
    # Defaults target Langfuse Cloud's free tier; point langfuse_host at a
    # self-hosted instance to swap targets without code changes.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
