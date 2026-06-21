# ConsultRAG — Architecture

**Status:** design baseline · **Last updated:** June 2026
**Owner:** [your name] · **Audience:** engineers and technical reviewers

A retrieval platform that lets analysts at a small healthcare / life-sciences
consulting firm ask questions across their own engagement material *and* the
current external market, and get answers that are grounded, **cited, and dated**
— without confidential client or patient data leaking between engagements or out
to third parties.

---

## 1. Purpose & scope

Consultants lose hours re-reading old decks, transcripts, and research to
reconstruct what is already known about a market, and an LLM alone can't help
because its knowledge is frozen at training time while consulting value is being
*current*. ConsultRAG addresses both halves:

- **Internal recall** — semantic + keyword search over the firm's proprietary
  research (slide decks, PDFs, market/secondary research, recorded client
  meetings), with answers traceable to the exact slide, page, or timestamp.
- **External freshness** — a live-data layer that pulls current market, company,
  and regulatory information from the web at query time, merged with internal
  results and clearly distinguished by recency.

**In scope (v1):** a deployable, multi-tenant service for a single small firm,
with the governance a healthcare-adjacent setting requires.
**Out of scope (v1):** agentic multi-hop research, knowledge graphs, and model
fine-tuning — see §13. These are deliberate roadmap items, not omissions.

## 2. Design principles

1. **Confidential by construction.** PII/PHI is removed *before* anything is
   embedded or stored; client identifiers never leave the firm's boundary, even
   on outbound web queries. Confidentiality is a property of the data flow, not a
   feature bolted on afterward.
2. **Every answer is cited and dated.** A consultant must defend each claim to a
   client. Unattributed claims are flagged, not shown as fact.
3. **Tenant isolation is non-negotiable.** One analyst can never retrieve another
   engagement's material through the assistant.
4. **Pluggable, not coupled.** Embedders, vector stores, LLMs, and search
   providers sit behind interfaces so any one can be swapped without touching the
   rest.
5. **Evaluated, not vibes.** Retrieval and answer quality are measured against a
   golden set on every change.
6. **Local-first, cloud-optional.** Defaults keep data on the firm's hardware;
   hosted models are an explicit, documented trade-off guarded by redaction.

## 3. System overview

```
  INGEST                                    QUERY
  ──────                                    ─────
  pptx · pdf · txt · audio                  analyst question
        │                                         │
        ▼                                         ▼
  ┌───────────┐                            ┌───────────────┐
  │  Loaders  │ slides+notes/pages/ts      │ Query Router  │ internal? external? both?
  └─────┬─────┘                            └───┬───────┬───┘
        ▼                                      │       │
  ┌───────────┐ PII/PHI removed here           │       ▼
  │ Redactor  │ BEFORE embedding               │  ┌──────────────┐  client names
  └─────┬─────┘                                │  │  Outbound    │  stripped before
        ▼                                      │  │  Sanitizer   │  hitting the web
  ┌───────────┐ +1-line LLM context per chunk  │  └──────┬───────┘
  │ Contextual│                                │         ▼
  │  Chunker  │                                │  ┌──────────────┐
  └─────┬─────┘                                │  │ Live Search  │ Tavily (dated,
        ▼                                      │  │  Provider    │ recency-filtered)
  ┌───────────┐ local sentence-transformers    │  └──────┬───────┘
  │ Embedder  │ (OpenAI text-embedding-3-large │         │
  └─────┬─────┘  opt-in via --embedder openai) │         │
  └─────┬─────┘                                ▼         │
        ▼                              ┌───────────────┐ │
  ┌───────────┐ NumPy (default)        │   Hybrid      │ │
  │  Vector   │◄───pgvector opt-in─────│  Retriever    │ │
  │   Store   │  dense + BM25 (RRF)    └───┬───────────┘ │
  │           │  (--store pgvector)        │             │
  └───────────┘                            ▼             │
                                     ┌──────────────┐    │
                                     │  Reranker    │    │
                                     │(cross-encoder)│   │
                                     └──────┬───────┘    │
                                            ▼            ▼
                                     ┌─────────────────────────┐
                                     │  Access Filter (RBAC +  │
                                     │  engagement isolation)  │
                                     └──────────┬──────────────┘
                                                ▼
                                     ┌─────────────────────────┐
                                     │  Merge internal+external│ tag source_type,
                                     │  + grounded synthesis   │ date; flag stale
                                     └──────────┬──────────────┘
                                                ▼
                                     cited, dated answer  ──►  Audit log + Langfuse trace

  Cross-cutting: OAuth2 auth · per-engagement scoping · append-only audit · Langfuse observability
```

## 4. Core components

| Component | Responsibility |
|---|---|
| **Loaders** | Parse pptx (slides + speaker notes), pdf (per page), text, and audio (local timestamped transcription) into provenance-tagged sections. |
| **Redactor** | Remove PII/PHI (email, phone, SSN, cards, MRN, NPI, IP) and custom client terms before indexing; emit counts to the audit log, never values. |
| **Contextual Chunker** | Sentence-aware, token-budgeted, overlapping chunks; prepend a one-line LLM-generated locator-context to each chunk before embedding. |
| **Embedder** | Default local sentence-transformers (`bge-small-en-v1.5`), consistent with the local-first principle (§2.6); OpenAI `text-embedding-3-large` is an opt-in, higher-quality alternative (`--embedder openai`), and an offline hash embedder covers zero-download demos/tests. |
| **Vector Store** | Default local NumPy cosine store, consistent with the local-first principle (§2.6); pgvector/Postgres is opt-in (`--store pgvector`) for SQL-level RBAC filtering and corpora too large to keep in memory. Pluggable interface (`add`/`search`/`save`/`load`/`all_chunks`). |
| **Hybrid Retriever** | Dense (vector) + sparse (BM25) candidates fused with Reciprocal Rank Fusion. |
| **Reranker** | Cross-encoder (`bge-reranker`) rescoring ~20 fused candidates to the final top-k. |
| **Query Router** | Classifies a question as internal / external / both. |
| **Outbound Sanitizer** | Strips engagement names and redaction terms from queries before they reach the web. |
| **Live Search Provider** | Tavily by default; returns dated, recency-filtered passages. Interface allows Exa/Brave swap. |
| **Result Merger + Synthesizer** | Unifies internal + external context tagged by source type and date; produces a grounded answer with per-claim citations and staleness flags. |
| **Access Control** | Engagement isolation + clearance, enforced at the DB query layer with an in-process policy backstop. |
| **Audit Log** | Append-only record of every ingest and query (who, what, when; redaction counts; what was stripped from outbound queries). |
| **Evaluation** | Retrieval metrics (hit@k, recall@k, MRR) + RAGAS-style faithfulness and answer relevancy against a golden set. |
| **Observability** | Langfuse traces: query, retrieved ids + scores, latency, token/cost. |
| **API** | FastAPI service; OAuth2 bearer auth; endpoints for ingest, query, draft, and structured-entity lookup. |

## 5. Data flows

**Ingestion:** `load → redact → contextual-chunk → embed → store`, attaching
engagement + clearance metadata. Redaction precedes embedding so the index holds
redacted text only.

**Query:** `authenticate → route → (sanitize → live search) and/or (hybrid
retrieve → rerank) → access filter → merge & date-tag → grounded synthesis →
audit + trace`. The router decides which retrieval paths run; the access filter
runs on internal results before they ever reach the LLM.

## 6. Security & governance model

| Threat | Control |
|---|---|
| PII/PHI persisted in the index | Redaction before embedding; index stores placeholders only. |
| Client intent leaked to the public web | Outbound query sanitizer strips client/engagement names before search. |
| Cross-engagement data access | RBAC + engagement scoping enforced at the SQL layer *and* in the policy backstop. |
| Unauthorized service access | OAuth2 bearer tokens validated against the provider's JWKS; claims map to roles/clearance. |
| No accountability trail | Append-only audit log of ingests and queries. |
| Sensitive data sent to third-party models | Local-first defaults; redaction guards any hosted-model path; web search is over public data only. |

Data-retention note: free-tier search/LLM providers may train on inputs, so real
client material is never sent to them — only sanitized, public-web queries go
out. Internal confidential text stays on local embeddings/store by default.

## 7. Retrieval design rationale

- **Hybrid over pure-dense:** vector search misses exact tokens (drug names,
  device models, billing codes, company names) that consulting queries hinge on;
  BM25 recovers them. Fused with RRF for a single ranked list.
- **Reranking:** a cross-encoder rescoring ~20 candidates to the best 5 is the
  highest-ROI quality lever; it judges query–passage relevance directly rather
  than via independent embeddings.
- **Contextual chunking:** prepending a short "where this sits" line per chunk
  before embedding measurably improves retrieval of passages that are ambiguous
  in isolation.
- **pgvector/Postgres (opt-in via `--store pgvector`):** appropriate for a small
  firm's corpus (well under the multi-million-vector range where approximate
  indexes like FAISS/Qdrant earn their keep), runs in one container, and lets
  access control be a SQL `WHERE` — applied as defense-in-depth *alongside*,
  not instead of, the in-process `AccessPolicy` check that runs for every
  backend. The local NumPy store remains the default for zero-infra demos and
  development.
- **Chunking params:** ~350-token windows, ~50-token overlap, sentence-aware —
  balances retrieval precision against fragmenting context.

## 8. Freshness / live-data design

The differentiator. Steps:

1. **Route.** Cheap LLM classifier (with rule-based fallback) decides whether the
   web is needed, avoiding wasted calls and noise in internal-only answers.
2. **Sanitize.** Strip client/engagement identifiers from the outbound query.
3. **Search.** Tavily with a recency filter; capture URL, title, published date,
   and extracted content. News-style endpoints for minute-level freshness.
4. **Merge & date-tag.** External results join internal chunks in one context
   set, each tagged `source_type` and `date`.
5. **Synthesize with recency awareness.** The answer cites internal and external
   sources distinctly and flags any source older than a configurable threshold as
   potentially stale.
6. **Cache.** TTL cache keyed by sanitized query to control cost and latency.

Provider is abstracted; Tavily is the default, Exa (semantic) and Brave
(independent index, no query logging) are documented swaps for privacy-sensitive
deployments.

## 9. Evaluation strategy

- A hand-labeled golden set of 50–100 question/answer pairs covering real use
  cases, version-controlled in `eval/`.
- Retrieval: hit@k, recall@k, MRR.
- Generation: RAGAS-style faithfulness and answer relevancy via an LLM judge.
- Operating rule: if faithfulness drops below ~0.9, fix retrieval before
  touching generation — most "hallucination" is actually wrong-context retrieval.
- Evaluation runs on every pipeline change; numbers are reported in the README.

## 10. Observability

Every query emits a Langfuse trace: the question, retrieved chunk ids and scores,
which retrieval paths ran, latency, and token/cost. This makes "why did it answer
that?" answerable on demand — a requirement for a system clients rely on.

## 11. Deployment

- **Compose stack:** `postgres` (pgvector) today; `api` (FastAPI) is roadmap
  (§13/§14). Langfuse tracing targets Langfuse Cloud's free tier by default
  (two API keys, no extra container) — self-hosting Langfuse's own stack
  (Postgres + ClickHouse + Redis/blob storage) is documented as a swap via
  `LANGFUSE_HOST` for teams that need data to stay fully on-prem, but isn't a
  default compose service given its footprint relative to this project's size.
  Models are *not* containerized — embeddings/LLM are API-based or run on the
  host — keeping image sizes small.
- **Secrets:** `.env` (gitignored) supplies OpenAI, Groq, Tavily, OAuth, and DB
  settings via a typed config module.
- **Dev environment:** Windows + Docker Desktop + VS Code; `docker compose up -d`
  for infra, offline mode available with zero keys for demos.

## 12. Technology choices

| Concern | Choice | Why | Alternative |
|---|---|---|---|
| Embeddings | Local sentence-transformers (default) | Local-first principle (§2.6); zero egress | OpenAI `text-embedding-3-large` (opt-in, higher quality, sends text off-machine) |
| Generation | Groq (fast) / OpenAI | Low latency, OpenAI-compatible | Local model (air-gapped) |
| Vector store | NumPy cosine store (default) | Local-first principle (§2.6); zero infra for demos | pgvector/Postgres (opt-in, `--store pgvector`: SQL-level RBAC filter, one container); FAISS/Qdrant at much larger scale |
| Sparse retrieval | BM25 (RRF fusion) | Recovers exact-term matches | Postgres full-text search |
| Reranker | cross-encoder `bge-reranker` | Local, no extra key | Hosted rerank API |
| Live search | Tavily | LLM-native, dated, free tier | Exa, Brave (privacy) |
| Auth | OAuth2 / JWT (JWKS) | Standard, provider-agnostic | — |
| Observability | Langfuse | Open-source, self-hostable | LangSmith |
| Eval | RAGAS-style + custom | Faithfulness + retrieval metrics | — |

## 13. Roadmap (deliberately out of v1)

- **Agentic retrieval:** query decomposition for multi-step research, with strict
  per-claim citation grounding to control synthesis hallucination. Adds latency
  and orchestration complexity.
- **GraphRAG:** a knowledge graph over extracted entities for relationship-aware
  questions ("which competitors share investors?").
- **Fine-tuning for house style:** RAG handles knowledge; a fine-tune could
  handle the firm's tone/format for drafts. Knowledge via RAG, behavior via
  fine-tuning.
- **Speaker diarization** for meeting audio.

## 14. Phased delivery plan

| Phase | Deliverable |
|---|---|
| 0 | Config + secrets + Postgres/pgvector via Docker |
| 1 | Hybrid retrieval + reranker + contextual chunking + faithfulness eval |
| 2 | pgvector backend + Langfuse observability |
| 3 | Live-data layer (router, sanitizer, Tavily, recency, cache) |
| 4 | FastAPI service + OAuth2 auth + engagement isolation |
| 5 | Structured extraction + cited deliverable drafting |

Each phase ships behind interfaces, keeps the offline demo working, and is
covered by tests run on every change.
