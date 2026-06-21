# ConsultRAG — a security-first knowledge assistant for consulting teams

A retrieval-augmented generation (RAG) system that lets analysts and consultants
ask questions across their own research material — client slide decks, market and
secondary research, PDFs, and recorded client meetings — and get grounded,
**cited** answers, without confidential client or patient data ever leaving the
machine or leaking between engagements.

Built as a local-first system: documents are parsed, **redacted of PII/PHI**,
chunked, embedded, and indexed entirely on local hardware. No client text is sent
to any third-party API unless you explicitly wire one in.

> Why this exists: while interning as an analyst I watched a lot of time go into
> re-reading old decks, transcripts, and research to reconstruct what was already
> known about a market. This is a working prototype of the tool I wished existed —
> with the confidentiality controls a consulting/healthcare setting actually needs.

---

## What it does

- **Multimodal ingestion** — PowerPoint (slides *and* speaker notes), PDF (per
  page), plain text/markdown, and meeting audio (local transcription with
  timestamps). Each passage keeps its provenance so answers can cite the exact
  slide, page, or timestamp.
- **Confidentiality by construction**
  - PII/PHI redaction (email, phone, SSN, credit cards w/ Luhn check, medical
    record numbers, NPI, IPs, plus custom client/codename terms) runs *before*
    anything is embedded or stored. The index holds redacted text only.
  - Role-based access control with per-engagement isolation and clearance levels,
    enforced at retrieval time so one analyst can't pull another client's material
    through the assistant.
  - Append-only audit log of every ingest and query (records redaction *counts*,
    never the redacted values).
- **Grounded answers** — the model is instructed to answer only from retrieved
  context and cite sources; every response carries its supporting chunks.
- **Hybrid retrieval** — dense cosine search fused with BM25 keyword search via
  Reciprocal Rank Fusion, with an optional cross-encoder reranker (`--rerank`)
  rescoring the fused candidates down to the final top-k.
- **Local by default** — local embeddings (sentence-transformers) and a local LLM
  (via Ollama). An offline extractive mode runs with zero model downloads.
  OpenAI `text-embedding-3-large` is available as an opt-in, higher-quality
  embedder (`--embedder openai`) — see "Egress notes" below.
- **Evaluated, not vibes** — a retrieval eval harness reports hit@k, recall@k, and
  MRR against a hand-labeled gold set.

## Architecture

```
                 ┌─────────────┐
  .pptx .pdf     │  Loaders    │  slides + notes / pages / timestamped audio
  .txt  audio ──▶│ (registry)  │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐   PII/PHI + custom terms removed here,
                 │  Redactor   │   BEFORE embedding. Index never sees raw PII.
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐   sentence-aware, token-budgeted, overlapping
                 │   Chunker   │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐   local sentence-transformers (CPU)
                 │  Embedder   │
                 └──────┬──────┘
                        ▼
                 ┌─────────────┐   local NumPy cosine store (default);
                 │ VectorStore │   pgvector/Postgres opt-in (--store pgvector)
                 └──────┬──────┘
                        ▼
  question ─▶ embed ─▶ retrieve ─▶ ACCESS FILTER ─▶ prompt ─▶ local LLM ─▶ cited answer
                                   (RBAC + clearance)            (Ollama)
```

## Quickstart

```bash
pip install -r requirements.txt

# 1. Ingest the included sample material (offline = no model download)
python scripts/ingest.py --path data/sample --engagement acme --clearance 2 --offline

# 2. Ask a question as an analyst cleared for that engagement
python scripts/query.py "What is the barrier to adoption?" \
    --roles analyst engagement:acme --clearance 2 --offline

# 3. Score retrieval quality
python scripts/run_eval.py --offline
```

To run for real (better answers): drop `--offline` to use local embeddings, and
add `--llm ollama` to `query.py` after installing [Ollama](https://ollama.com) and
running `ollama pull llama3.1:8b`. For meeting audio, `pip install faster-whisper`.
Add `--rerank` to `query.py`/`run_eval.py` for cross-encoder reranking of the
fused candidates (downloads `BAAI/bge-reranker-base` on first use).

### Egress notes (what leaves the machine, and when)

| Flag | Default? | What it does | What leaves the machine |
|---|---|---|---|
| *(none)* | yes | Local sentence-transformers embeddings + hybrid (dense+BM25) retrieval against the local NumPy store | nothing |
| `--offline` | opt-in | Forces the hash embedder and `--store numpy`; zero network calls, zero model downloads; disables `--rerank` | nothing |
| `--embedder openai` | opt-in | OpenAI `text-embedding-3-large` embeddings | chunk/query text, to OpenAI's API |
| `--store pgvector` | opt-in | Postgres+pgvector vector store (via `docker compose up -d`) with a SQL-level RBAC filter as defense-in-depth | chunk text/vectors, to your own Postgres container — nothing external |
| `--rerank` | opt-in | Local cross-encoder reranking | nothing at query time (model weights download once) |
| Langfuse keys in `.env` | opt-in | Query tracing (question, retrieved ids+scores, latency, token usage) | question + answer text, to Langfuse Cloud (or your self-hosted instance) |

`--offline` is mutually exclusive with `--embedder openai`, `--store pgvector`,
and `--rerank` — combining them is a CLI error, not a silent fallback.

## Local setup (Windows + Docker Desktop)

The offline demo above needs none of this — it's only for the optional
Postgres/pgvector backend and hosted-API config.

1. **Install deps** (adds `pydantic-settings`/`python-dotenv` for config loading):

   ```bash
   pip install -r requirements.txt
   ```

2. **Start Postgres with pgvector** (requires Docker Desktop, running):

   ```bash
   docker compose up -d
   ```

   This starts a `pgvector/pgvector` Postgres container, enables the `vector`
   extension via `docker/init/01-enable-pgvector.sql`, and persists data in a
   named Docker volume (`pgdata`) — nothing is written into the repo.
   Stop it with `docker compose down` (add `-v` to also drop the volume).

3. **Configure environment** — copy the example file and fill in only what you
   need; every value defaults to "off"/local, so an empty `.env` is fine:

   ```bash
   copy .env.example .env
   ```

4. **Run the existing offline demo** exactly as in the Quickstart above — it
   does not read `.env`, Postgres, or any API key:

   ```bash
   python scripts/ingest.py --path data/sample --engagement acme --clearance 2 --offline
   python scripts/query.py "What is the barrier to adoption?" --roles analyst engagement:acme --clearance 2 --offline
   python scripts/run_eval.py --offline
   ```

`src/consultrag/config.py` exposes a `Settings` object (via `pydantic-settings`)
for `OPENAI_API_KEY`, `GROQ_API_KEY`, `TAVILY_API_KEY`, `DATABASE_URL`,
`OAUTH_ISSUER`/`OAUTH_AUDIENCE`/`OAUTH_JWKS_URL`, `LANGFUSE_PUBLIC_KEY`/
`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST`, and the existing Ollama settings — all
optional, all defaulted, and not imported by any offline code path today.

### Using the pgvector backend

```bash
pip install "psycopg[binary]" pgvector   # not installed by default
docker compose up -d                     # starts Postgres+pgvector

# Provision the schema for the embedding dimension you'll ingest with
# (384 = local default, 256 = hash, 3072 = openai). Re-run if you change
# embedders, or pick a different --table.
python scripts/migrate_pg.py --dim 384

python scripts/ingest.py --path data/sample --engagement acme --clearance 2 --store pgvector
python scripts/query.py "What is the barrier to adoption?" \
    --roles analyst engagement:acme --clearance 2 --store pgvector
```

RBAC is checked twice against this backend: a SQL `WHERE` filter on
`engagement`/`clearance` runs first (defense-in-depth, narrows what ever
leaves Postgres), then the same in-process `AccessPolicy` check that runs for
every backend. Neither replaces the other.

To verify the migration didn't change retrieval *behavior* (not RBAC — see
`consultrag.eval.evaluate`'s docstring), run the same eval set against both
backends and compare:

```bash
python scripts/run_eval.py --offline                       # numpy baseline
python scripts/run_eval.py --embedder hash --store pgvector # same embedder, pgvector backend
```

hit@k/recall@k/MRR should match within float tolerance.

### Query tracing (Langfuse)

Tracing is a no-op until configured. To enable it: sign up for
[Langfuse Cloud's free tier](https://langfuse.com), drop your public/secret
key into `.env` as `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, and
`pip install langfuse`. Every `RAGEngine.answer()` call then emits a trace
with the question, retrieved chunk ids + scores, latency, and token usage
(when the LLM backend reports it — currently `OllamaLLM` only). Self-hosting
Langfuse is a drop-in swap via `LANGFUSE_HOST`; it isn't a docker-compose
service here given its footprint (its own Postgres + ClickHouse + Redis)
relative to this project's size.

## Design decisions (and the trade-offs)

- **Redaction before indexing, not at display time.** Stronger guarantee — raw PII
  is never persisted — at the cost of not being able to "un-redact" later.
- **Vector store written from scratch on NumPy, default backend.** Keeps everything
  local and makes the retrieval math inspectable. `PgVectorStore` (`--store
  pgvector`) is available when the corpus outgrows in-memory cosine search or
  you want SQL-level RBAC filtering as defense-in-depth.
- **Local LLM by default.** Confidentiality over raw answer quality; the LLM
  interface is pluggable if you accept a hosted model.
- **Sentence-aware overlapping chunks (~350 tokens, ~50 overlap).** Balances
  retrieval precision against context fragmentation.

## Tests & evaluation

```bash
python -m pytest tests/ -q        # unit + end-to-end (incl. access-control) tests
python scripts/run_eval.py --offline
```

Retrieval metrics are reported on `eval/eval_set.jsonl`. Replace the sample set
with a real 20–30 question gold set from your own corpus to get meaningful numbers.

## Roadmap

- Speaker diarization for meeting audio (pyannote)
- Groq-backed contextual chunking and a RAGAS-style/LLM-judge generation eval
- Presidio-based NER redaction for names/orgs/locations
- A small web UI for analysts

## Project layout

```
src/consultrag/
  ingestion/    loaders (pptx, pdf, text, audio) + registry
  security/     redaction (PII/PHI) + RBAC access control
  chunking.py   sentence-aware overlapping chunker
  embeddings.py local, hash (offline), and OpenAI embedders
  vectorstore.py  local NumPy cosine vector store with persistence (default)
  pgvectorstore.py  Postgres+pgvector store, opt-in via --store pgvector
  retrieval.py  hybrid (dense+BM25) retrieval fused with RRF
  reranking.py  optional cross-encoder reranker
  tracing.py    Langfuse query tracing (no-op unless configured)
  config.py     typed settings loaded from .env (pydantic-settings)
  pipeline.py   ingest orchestration (load→redact→chunk→embed→store)
  rag.py        retrieve→access-filter→rerank→prompt→LLM→cited answer
  audit.py      append-only audit log
  eval.py       hit@k / recall@k / MRR (hybrid retrieval, RBAC-free by design)
scripts/        ingest.py, query.py, run_eval.py, migrate_pg.py
tests/          redaction, chunking, retrieval, reranking, pgvectorstore,
                end-to-end access control
```
