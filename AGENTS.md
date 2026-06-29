# Repository Guidelines

Guide for AI assistants working in `ai-study-hub-rag-service`. Everything below is grounded in the current source tree.

## Project Overview

**AI Study Hub RAG Service** — a FastAPI / Python service that powers the AI features of the AI Study Hub platform. It owns document **ingestion** (download → parse → parent-child chunk → embed → index), **hybrid retrieval** (BM25 + pgvector dense + Jina cross-encoder re-rank), and **RAG generation** (Gemini) with numeric `[N]` citations. It stores vectors in PostgreSQL + pgvector and shares one `aistudyhub` database (plus one `INTERNAL_API_SECRET`) with the sibling **Java backend** (`ai-study-hub-api`). Runs on uvicorn, port `8000`.

## Architecture & Data Flow

Single FastAPI app (`main.py`) exposing REST endpoints. There is no DB ORM layer — persistence is raw `psycopg2` over a process-wide `ThreadedConnectionPool` (`app/database/pool.py`). External LLM/embedding/rerank clients are process-wide singletons (`app/core/clients.py`), warmed at startup.

```
Java backend ──HTTP──▶ FastAPI (main.py)
                          │
   ingest endpoints       │           chat endpoints
   POST /rag/process      │           POST /chat  ─▶ router (LLM: SUMMARY vs QA)
   POST /rag/extract      │                              │
   POST /rag/index        │              QA branch: retrieve_documents()
   PATCH /rag/.../visibility│              ├─ BM25 (parent docs, filtered by document_id)
   DELETE /rag/documents/{id}│             ├─ dense pgvector cosine (HNSW, k=25)
                          │              ├─ EnsembleRetriever (BM25 0.3 / dense 0.7)
   ◀── callback (X-Internal-Secret) ─     ├─ Jina re-rank → top context
        send_callback() ──▶ backend       └─ Gemini generation → [N] citations
```

**Ingestion is two-phase** (`app/services/ingestion.py`):
- `_extract`: download presigned file → load by extension → enrich metadata (page/chunk citations + `document_id`) → parent-child chunk via `ParentDocumentRetriever._split_docs_for_adding` → store parent docs in `LocalFileStore` (`parent_docs_store/`) → insert child chunks into `document_chunks` with **`embedding = NULL`**.
- `_index`: `embed_pending_chunks(document_id)` — embed all `embedding IS NULL` chunks (one `embed_documents` call, 1536-dim Gemini) + per-row `UPDATE` → `update_bm25()`. Idempotent.
- `process_document_task` (PRIVATE docs) = `_extract` + `_index` + summary, then callback `SUCCESS`. `extract_document_task` (PUBLIC docs) = `_extract` only + summary, callback `EXTRACTED`. `index_document_task` (after approval) = `_index`, callback `SUCCESS`.

Callbacks (`send_callback`) POST to `BACKEND_CALLBACK_URL` (`/api/v1/internal/documents/callback`) with header `X-Internal-Secret`, body `{document_id, status, summary}`, retried 3× with exponential backoff.

## Key Directories

```
main.py                     FastAPI app: endpoints, request models, startup warmup
app/
├── core/
│   ├── config.py           Settings (DATABASE_URL, BACKEND_CALLBACK_URL, INTERNAL_API_SECRET, ...)
│   ├── clients.py          Singleton Gemini LLM + Jina reranker (process-wide)
│   └── performance.py      Instrumentation: start_trace() / stage() / trace.emit() → logs/performance.log
├── database/
│   ├── pool.py             ThreadedConnectionPool + db_connection() context manager (rollback on exit)
│   ├── vector_store.py     Custom PostgresVectorStore over pgvector (add_texts, embed_pending_chunks,
│   │                       delete_by_document_id, update_chunk_visibility, similarity_search_by_vector)
│   └── document_store.py   document lookups (summary, title, user document ids)
├── services/
│   ├── ingestion.py        _extract / _index / process / extract / index tasks + delete + visibility
│   ├── retrieval.py        Hybrid retrieval: BM25 + dense (EnsembleRetriever) + Jina re-rank
│   ├── router.py           LLM router: SUMMARY vs QA branch
│   └── generation.py       Gemini RAG answer with [N] citation markers
└── pipeline/
    └── dependencies.py     Singletons: embeddings, vectorstore, parent/child splitters,
                            ParentDocumentRetriever, LocalFileStore docstore, BM25 state (initialize/update_bm25)
parent_docs_store/          Persistent LocalFileStore for parent docs (keyed by uuid) — mounted volume
temp/                       Downloaded source files (cleaned up after ingest) — mounted volume
logs/                       performance.log (RotatingFileHandler) — mounted volume
initdb.sql                  Full DDL (shared with backend): document_chunks.embedding vector(1536) + HNSW cosine
requirements.txt            Pinned deps — LangChain 0.3.x (do NOT bump to 1.x)
Dockerfile / docker-compose.yml   python:3.11-slim image; joins external ai-study-hub-network
```

## Development Commands

Python + uvicorn. **There is no Java/Node here — this is a pure Python service.**

```bash
# Local dev (from the repo root) — reload on change
uvicorn main:app --reload --host 0.0.0.0 --port 8000
# or
python main.py

# Install deps (use a virtualenv)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the whole stack via Docker (builds image, serves :8000)
docker compose up --build -d
```

- **Needs a running PostgreSQL 16 + pgvector** (`aistudyhub` DB, `document_chunks` table with `vector(1536)` + HNSW index) — normally provided by the backend's `docker-compose.yaml`. `initialize_bm25()` at startup reads parent docs from `parent_docs_store/`; if empty, BM25 starts empty (added as docs are indexed).
- **Needs env / API keys** (see Runtime below). Copy them into `.env` — `load_dotenv()` loads it.
- **Swagger**: `http://localhost:8000/docs`.

## Code Conventions & Common Patterns

**Singletons.** External clients (`llm`, `embeddings`, `reranker`) and pipeline objects (`vectorstore`, `store`, `retriever`, splitters, `state`) are created **once at import** in `app/core/clients.py` and `app/pipeline/dependencies.py`, then imported everywhere. Never instantiate per-request — they hold HTTP connection pools / TLS state (a former per-request `new ChatGoogleGenerativeAI(...)` cost ~50-150ms of setup each). `_warmup_clients()` at startup primes Gemini (avoids a ~14s cold-start on the first real request).

**DB access.** Always borrow from the pool via the `db_connection()` context manager (`app/database/pool.py`) — it `rollback()`s in `finally` (returns the connection clean to the pool, even for reads) and is closed by `atexit`. `ThreadedConnectionPool` is used because handlers are sync `def` (see below). `minconn=1`, `maxconn=DB_POOL_MAX` (default 20).

**Sync handlers.** Endpoints use plain `def` (not `async def`) — FastAPI runs them in a threadpool, so blocking I/O (Gemini, Jina, psycopg2) does not stall the event loop. Keep new endpoints `def` unless they're genuinely async.

**Two-phase extract/index (moderation gate).** Public docs are extracted with `embedding = NULL` and only embedded after the backend approves them. `similarity_search_by_vector` filters `WHERE embedding IS NOT NULL`, so extracted-but-not-indexed chunks are never returned. Never remove that filter.

**Parent-child retrieval.** `_extract` reuses `ParentDocumentRetriever._split_docs_for_adding` so child chunks carry `metadata["doc_id"]` = parent uuid (LangChain `MultiVectorRetriever.id_key = "doc_id"`). Retrieval matches a child by vector, then fetches its parent from `LocalFileStore`. Do not change the `doc_id` key without updating both sides. Splitters: parent 1000/200, child 200/50.

**Instrumentation.** Wrap request work in `start_trace(label, **meta)` and sub-steps in `with stage("name"):`; the trace is emitted to `logs/performance.log` + console (`ENABLE_PERF_LOG=1` default). The codebase labels optimizations as `S2` (singletons), `S3` (sync handlers/threadpool), `S4` (connection pool), `S6` (BM25 pre-filter), `S8` (multi-query off) — match these markers when extending.

**Error → callback.** Ingestion tasks catch exceptions and `send_callback(document_id, "FAILED")` rather than raising (they run in `BackgroundTasks`, off the request thread). Always send a terminal callback so the backend's status machine doesn't stall.

**Callbacks to backend.** `send_callback` uses stdlib `urllib.request` (not `requests`/`httpx`) with the `X-Internal-Secret` header; 3 retries, exponential backoff.

## Important Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app: all endpoints (`/rag/process`, `/rag/extract`, `/rag/index`, `/rag/documents/{id}/visibility`, `/rag/documents/{id}`, `/chat`, `/chat/retrieve`), request models, startup (BM25 init + client warmup) |
| `app/services/ingestion.py` | Two-phase `_extract`/`_index` + `process/extract/index_document_task`, `delete_document`, `update_document_visibility`, `send_callback`, `generate_document_summary` |
| `app/services/retrieval.py` | `retrieve_documents()` — hybrid BM25+dense (`EnsembleRetriever`) + Jina rerank; BM25 pre-filtered by `document_id` |
| `app/services/router.py` | `route_chat_request()` — LLM classifies SUMMARY vs QA |
| `app/services/generation.py` | `generate_rag_response()` — Gemini answer with `[N]` citation markers |
| `app/database/vector_store.py` | Custom `PostgresVectorStore`: `add_texts` (embed), `add_texts_without_embedding` (extract), `embed_pending_chunks` (index), `delete_by_document_id`, `update_chunk_visibility`, `similarity_search_by_vector` (`embedding IS NOT NULL`) |
| `app/pipeline/dependencies.py` | Pipeline singletons: `embeddings` (Gemini 1536-dim), `vectorstore`, `store` (LocalFileStore), `retriever` (ParentDocumentRetriever), splitters, BM25 `state` + `initialize_bm25`/`update_bm25` |
| `app/database/pool.py` | `ThreadedConnectionPool` + `db_connection()` context manager |
| `app/database/document_store.py` | `get_document_summary` / `get_document_title` / `get_user_document_ids` |
| `app/core/clients.py` | Singleton `llm` (`gemini-2.5-flash-lite`) + `reranker` (`jina-reranker-v3`, top_n=5) |
| `app/core/config.py` | `Settings`: `DATABASE_URL`, `BACKEND_CALLBACK_URL`, `INTERNAL_API_SECRET`, `TEMP_DIR` |
| `app/core/performance.py` | `start_trace` / `stage` / `PerformanceTrace.emit` → `logs/performance.log` (`ENABLE_PERF_LOG`) |
| `initdb.sql` | Shared DDL: `document_chunks(id, document_id, chunk_index, content, embedding vector(1536), metadata jsonb, page_number)` + `CREATE EXTENSION vector` + HNSW `vector_cosine_ops` index |
| `requirements.txt` | Pinned: `fastapi`, `uvicorn`, **`langchain>=0.3,<0.4` (pinned — 1.x breaks)**, `langchain-google-genai`, `psycopg2-binary`, `rank_bm25`, `pypdf`, `docx2txt`, `python-dotenv` |
| `Dockerfile` / `docker-compose.yml` | `python:3.11-slim`; container `ai-study-hub-rag-service` on external `ai-study-hub-network`; mounts `parent_docs_store/`, `temp/`, `logs/` |

## Sibling Service: Backend API (Java)

The Java backend (`~/code/ai-study-hub-api`, Spring Boot 4.0.6) is the API gateway and owns `documents`/`users`/`chat_sessions`/etc. This RAG service **owns `document_chunks`** (writes embeddings + metadata). The two share one PostgreSQL `aistudyhub` DB and one `INTERNAL_API_SECRET`.

**Contract (this service's side):**
- Receives `POST /api/v1/rag/process` (private: extract+index), `/extract` (public: extract only), `/index` (after approval: embed pending), `PATCH /rag/documents/{id}/visibility`, `DELETE /rag/documents/{id}`, `POST /api/v1/chat`, `/chat/retrieve` — all from the backend over the shared network.
- Sends `POST` to `${BACKEND_CALLBACK_URL}` (= backend `/api/v1/internal/documents/callback`) with `X-Internal-Secret: ${INTERNAL_API_SECRET}`, body `{document_id, status: SUCCESS|EXTRACTED|FAILED, summary}`.

**Gotchas:**
- `INTERNAL_API_SECRET` here must equal the backend's `app.internal.secret`, else every callback is rejected with 403.
- **The backend reads `document_chunks` read-only** (its `DocumentChunkRepository`) for moderation — it never writes this table. Only this service writes `document_chunks`.
- The backend gates which `document_id`s reach `/chat` (only `COMPLETED` docs), so this service does not need to filter retrieval by document status — but it does filter `embedding IS NOT NULL` as a safety net.
- See the backend's `AGENTS.md` for the full document lifecycle / moderation flow.

## Runtime / Tooling Preferences

- **Runtime**: Python. **`Dockerfile` targets `python:3.11-slim`** (production). Note the local `.venv` in this checkout is **Python 3.9** (EOL) — it works but emits Google `FutureWarning`s; prefer creating a 3.11+ venv locally to match the image.
- **Server**: uvicorn (`main:app`). `python main.py` runs uvicorn with `--reload`.
- **Dependencies**: `pip install -r requirements.txt`. **LangChain is pinned to 0.3.x — do not bump to 1.x** (it removed `langchain.storage`, reshuffled `langchain.retrievers`, etc.; this code targets the 0.3 API). ChromaDB is intentionally **not** used — vectors live in pgvector via the custom `PostgresVectorStore`.
- **Container**: `docker-compose.yml` builds `.` and joins the **external** `ai-study-hub-network` (created by the backend's compose). Mounts `parent_docs_store/`, `temp/`, `logs/` so parent docs and logs survive restarts.
- **External APIs**: Google Gemini (LLM `gemini-2.5-flash-lite`, embeddings `gemini-embedding-001` forced to **1536 dims**) + Jina (`jina-reranker-v3`). Keys via env (`GOOGLE_API_KEY` consumed by langchain-google-genai, `JINA_API_KEY`).
- **Env vars** (`.env`, loaded by `dotenv`): `DATABASE_URL`, `BACKEND_CALLBACK_URL`, `INTERNAL_API_SECRET`, `GOOGLE_API_KEY`, `JINA_API_KEY`, `ENABLE_MULTI_QUERY` (default `0` — multi-query costs ~6s/extra LLM call), `DB_POOL_MAX` (default 20), `ENABLE_PERF_LOG` (default `1`), `TEMP_DIR` (default `temp`). Never commit `.env`.

## Testing & QA

- **No automated tests** — there is no `tests/` directory and no `pytest`/`unittest` in `requirements.txt`. Verification is manual: run uvicorn, hit `/docs`, and exercise an endpoint with a real `document_id`/`file_url`.
- **Performance log**: `logs/performance.log` (rotating) records per-request stage timings via `start_trace`/`stage`/`emit`. Check it to profile retrieval latency (embed_query, dense_sql, bm25_build, rerank, generation).
- **Local sanity checks before changing ingestion/retrieval**: confirm `initialize_bm25` logs the parent-doc count at startup, and that `document_chunks` rows get `embedding` filled after `/index` (a `NULL` after a successful `/index` means `embed_pending_chunks` failed).
