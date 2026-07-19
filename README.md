# ComplianceHub

Multi-tenant RAG platform for auditing corporate documentation (contracts, policies, ISO standards) against regulatory requirements.

**Stack:** FastAPI (async) · PostgreSQL + pgvector · RabbitMQ + Celery · Redis · Neo4j (GraphRAG) · MinIO · Groq LLM · Ragas

## Architecture

```
                        ┌─────────────┐
   client ──HTTP──────▶ │  FastAPI    │────────────┐
                        │  (async)    │            │
                        └──┬───────┬──┘            ▼
              JWT + RLS    │       │         ┌──────────┐
                           ▼       │ publish │ RabbitMQ │
                    ┌──────────┐   └────────▶│ (broker) │
                    │ Postgres │             └────┬─────┘
                    │ +pgvector│                  │ consume
                    │  (RLS)   │             ┌────▼─────┐     ┌───────┐
                    └──────────┘             │  Celery  │────▶│ MinIO │
                           ▲                 │  workers │     └───────┘
                           │                 └────┬─────┘
                    ┌──────┴─────┐                │
                    │   Redis    │◀───results─────┤
                    │(cache+res.)│                ▼
                    └────────────┘          ┌──────────┐
                                            │  Neo4j   │
                                            │(GraphRAG)│
                                            └──────────┘
```

### Key design decisions

**Multi-tenancy via PostgreSQL Row-Level Security.** Every tenant-scoped table has an RLS policy comparing `tenant_id` with the `app.current_tenant_id` GUC. The application binds the tenant per-transaction via `set_config(..., true)` — the SET LOCAL equivalent that accepts bind parameters (see `app/core/database.py`). Isolation is enforced by the database itself — a buggy query cannot leak another tenant's rows. Crucially, the app connects as the non-superuser `app_user` role (`docker/postgres-init/`): superusers bypass RLS entirely, so migrations run as the admin role (`ALEMBIC_DATABASE_URL`) while API and workers run RLS-restricted.

**RabbitMQ as Celery broker** (Redis kept for cache + result backend): real message acks (`task_acks_late`), dead-letter exchange for poisoned messages, separate queues (`ingestion` / `graph` / `notifications`) so heavy document parsing never starves lightweight notifications.

**MinIO object storage** for original documents, namespaced by `{tenant_id}/{document_id}/`.

**Hierarchical chunking.** Parsers (PyMuPDF, python-docx) emit heading-aware sections; chunks never cross section boundaries, and each chunk stores its heading breadcrumb ("Data Policy > Retention") which is prepended at embedding time — a chunk saying "the period is 5 years" still embeds near queries about the policy named only in its heading. PDF headings are detected by font-size heuristic; DOCX uses real `Heading N` styles and keeps tables in document order.

**Embeddings via fastembed (ONNX).** Same BGE weights as sentence-transformers but no torch — the worker image stays ~10x smaller and CPU inference is faster. Vectors land in pgvector under an HNSW index (no training step, correct on a growing table, unlike IVFFlat).

**Hybrid retrieval: vector + full-text → RRF → cross-encoder.** Vector search (pgvector HNSW) catches paraphrases but misses exact identifiers; Postgres FTS (generated tsvector column + GIN, `websearch_to_tsquery`) nails exact terms ("ISO 27001", "Article 30") but not semantics. Reciprocal Rank Fusion merges the two rankings without score calibration — cosine distances and ts_rank live on incomparable scales, ranks do not. The fused top candidates then go through a BGE cross-encoder reranker (fastembed/ONNX): far more accurate than the bi-encoder, but O(candidates), which is why it never sees the whole corpus. `POST /api/v1/search` returns cited chunks (document, section breadcrumb, page).

**GraphRAG as a third retrieval signal.** After ingestion, a separate Celery task (own queue) extracts compliance entities from each chunk — a deterministic regex layer (ISO 27001, GDPR, "Article 30") that works with no API key, plus an optional LLM layer (Groq; Ollama is a base_url swap in `app/core/llm.py`) — and builds a Neo4j graph: `(Chunk)-[:MENTIONS]->(Entity)-…`. At query time, regex entities from the query are matched in the graph; chunks mentioning them score 1.0, chunks reached via 1-hop co-occurrence (derived through Chunk bridges at query time, never materialized) score 0.4. That ranking enters RRF as a third source next to vector and FTS. Neo4j Community has no RLS, so tenant isolation there is explicit `tenant_id` filtering in every query — a stated tradeoff vs the Postgres guarantee; graph downtime degrades search quality, never availability (the source is wrapped, and hydration re-enforces status/type filters Postgres-side).

**CRAG agent behind `POST /api/v1/ask`.** Plain RAG's failure mode is confidently answering from plausible-but-irrelevant chunks. The corrective loop: retrieve → grade every chunk in one batched LLM call → if too few survive, rewrite the query and re-retrieve → still too few, fall back to Tavily web search (optional) → generate with numbered context blocks. The generation prompt forbids uncited claims and invented regulation numbers; the response carries structured citations (document, section, page — or URL for web sources), the rewritten query, and a `low_confidence` flag when nothing relevant was found anywhere. Grading is deliberately fail-open: a broken grader call passes all chunks through — answering from unfiltered context beats refusing because a meta-call failed.

**Evaluation: RAGAS metrics, natively implemented.** `POST /api/v1/evaluation/runs` queues a run (own Celery queue) that pushes a golden dataset — or a caller-supplied one — through the *production* /ask pipeline and judges each answer: faithfulness (fraction of answer claims supported by context), answer relevancy (cosine between the question and questions regenerated from the answer), context precision (Average Precision over the ranked contexts — relevance must also be ranked high) and context recall (fraction of ground-truth statements the context can support). Implemented directly on our LLM abstraction rather than via the `ragas` library — same paper definitions, no langchain stack, unit-testable math. Metrics land per-question in Postgres (RLS-protected, NULL ≠ 0 so uncomputable metrics don't poison averages); `GET /evaluation/runs` serves per-run aggregates.

**PII never leaves the trust boundary unmasked.** Before any text reaches the LLM API or web search, a masking layer replaces emails, phones, Luhn-validated card numbers, IBANs and IPs with typed placeholders. The default engine is regex-based (deterministic, zero heavy deps — ISO dates and "Article 30" survive untouched); Presidio (NER, better recall on names) is an optional extra selected by config. The tenant's own API responses stay unmasked — the reader is authorized to see their documents, the model provider is not.

**Ingestion is asynchronous and idempotent.** Upload returns `202` with a PENDING document; a Celery task (RLS-bound via `SET LOCAL`, same as the API) drives PENDING → PROCESSING → READY | FAILED. `task_acks_late` means a crashed worker's message is re-delivered, so the task deletes the document's chunks before inserting — re-runs converge instead of duplicating. Parse errors are permanent (FAILED, no retry); infrastructure errors retry with backoff and dead-letter after `max_retries`.

## Quickstart

```bash
cp .env.example .env        # add GROQ_API_KEY / TAVILY_API_KEY
make up                     # build + start all services
make migrate                # apply Alembic migrations
make seed                   # demo tenant + policy documents (waits for ingestion)
open http://localhost:8000/docs
```

## API surface

| Endpoint | What it does |
|---|---|
| `POST /api/v1/auth/register` / `login` / `refresh` | tenant + JWT auth |
| `POST /api/v1/documents` | upload PDF/DOCX/MD/TXT → async ingestion |
| `POST /api/v1/documents/import` | import from URL / Google Drive share link |
| `POST /api/v1/search` | hybrid search (vector + FTS + graph → RRF → reranker) with citations |
| `POST /api/v1/ask` | CRAG agent: graded, corrected, cited answers |
| `POST /api/v1/evaluation/runs` | score the pipeline with RAGAS metrics (golden or custom dataset) |
| `GET /api/v1/evaluation/runs` | per-run metric averages |

The demo flow after `make seed`: login as `admin@demo.io` / `demo-password-1`
(slug `demo`), then ask *"How long is personal data retained?"* — the answer
cites the retention section of the seeded policy. `POST /evaluation/runs {}`
scores the golden dataset against those same documents. Slack notifications
(ingestion/evaluation outcomes) activate when `SLACK_WEBHOOK_URL` is set.

Service UIs: RabbitMQ management http://localhost:15672 · Neo4j browser http://localhost:7474 · MinIO console http://localhost:9001

Postgres is published on host port **5433** (not 5432) to avoid clashing with a natively installed PostgreSQL.

## Testing

```bash
make test               # unit tests (SQLite, fast)
make test-integration   # RLS isolation tests against real Postgres
make lint
```

## Roadmap

- [x] Phase 1 — scaffold: infra, auth (JWT), multi-tenancy (RLS), Celery/RabbitMQ, CI
- [x] Phase 2 — ingestion pipeline: upload → parse (PDF/DOCX) → hierarchical chunking → embeddings → pgvector
- [x] Phase 3 — hybrid retrieval: vector + full-text → RRF → cross-encoder reranking → metadata filters
- [x] Phase 4 — GraphRAG: entity extraction → Neo4j knowledge graph → graph-augmented retrieval
- [x] Phase 5 — CRAG agent: relevance grading → query rewrite → Tavily web-search fallback → cited answers
- [x] Phase 6 — evaluation (RAGAS metrics + /evaluation API) + PII privacy layer (regex/Presidio)
- [x] Phase 7 — polish: demo seed script, Slack notifications, URL/Google Drive import
