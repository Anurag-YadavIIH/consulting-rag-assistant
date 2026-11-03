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

    # OIDC authentication (auth/oidc.py). Provider-agnostic: issuer and
    # jwks_uri are read from the discovery document at oauth_discovery_url,
    # never hardcoded — Google by default, but any compliant OIDC provider
    # works by pointing this at its discovery URL. oauth_audience is your
    # OAuth client ID (the token's `aud` claim must match it).
    oauth_discovery_url: str = "https://accounts.google.com/.well-known/openid-configuration"
    oauth_audience: str | None = None

    # App session token (auth/app_token.py), issued at POST /auth/login after
    # Google/OIDC verification succeeds. Authentication (who, Stage 2) and
    # authorization (what, authz/repository.py) stay separate even here — the
    # app token's claims are populated FROM the authz store, never the reverse.
    app_jwt_secret: str | None = None
    dev_auth_bypass: bool = False
    # Must explicitly be "development"/"dev" for DEV_AUTH_BYPASS to be
    # permitted (auth/dev_bypass.py). Defaults to None (unset), which DENIES
    # bypass — this is a whitelist, not "anything that isn't production".
    app_env: str | None = None

    # Langfuse query tracing (tracing.py). Unset = tracing is a no-op.
    # Defaults target Langfuse Cloud's free tier; point langfuse_host at a
    # self-hosted instance to swap targets without code changes.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # CORS allowlist for browser-based clients (e.g. frontend/, the Next.js
    # demo client) — comma-separated origins. Defaults to empty, which means
    # CORS allows nothing: same fail-closed posture as APP_JWT_SECRET/APP_ENV
    # above. Set CORS_ALLOWED_ORIGINS=http://localhost:3000 for local
    # frontend dev; never trust a hardcoded origin in app code.
    cors_allowed_origins: str = ""

    # Largest accepted POST /ingest/upload file, in MB (413 above it). The
    # whole request still reaches the app before this check runs; a hard cap
    # on request size belongs at the proxy/load balancer.
    max_upload_mb: int = 25
    # Cap on an upload's extracted text, in chunks (about 350 tokens each).
    # Embedding ran at about 3 chunks a second on one vCPU, so 150 chunks fit
    # well inside CloudFront's 60 second origin timeout on AWS. Checked
    # before embedding, so an oversized document costs no embedding time.
    max_upload_chunks: int = 150

    # Team access (auth/access_settings.py, authz/team.py). Comma-separated;
    # malformed values make the app refuse to start.
    # Emails that become a global admin at their first verified sign-in.
    initial_admin_emails: str = ""
    # When set, only these domains may sign in, plus invited emails and
    # initial_admin_emails.
    allowed_email_domains: str = ""
    # Days an invitation stays usable.
    invitation_ttl_days: int = 14

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


settings = Settings()
